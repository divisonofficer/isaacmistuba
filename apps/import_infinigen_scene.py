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
import hashlib
import json
import math
import shutil
import struct
import time
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

# Ceiling-light emitter geometry. Render variance from an area light scales
# inversely with the solid angle it subtends, so a few small intense fixtures
# produce fireflies in the far/dark parts of a room. Ceiling emitters are tagged
# `emitter_shape="ceiling_panel"` so the renderer builds a wide DOWNWARD-facing
# flat rectangle (all emission into the room, no 6-face cube waste / ceiling
# embedding) — large flat area = low-variance, even fill. We also DIVIDE radiance
# by the area increase so luminous power is conserved (same brightness, less
# noise). Old geometry [0.3, 0.08, 0.3] is the power-conservation baseline; the
# y dimension is unused for the flat panel but kept for the authoring record.
LIGHT_SIZE_M = [0.6, 0.08, 0.6]
_LIGHT_AREA_BASELINE = 0.3 * 0.3
_LIGHT_AREA_FACTOR = (LIGHT_SIZE_M[0] * LIGHT_SIZE_M[2]) / _LIGHT_AREA_BASELINE

# Place the panel just below the ceiling so it never embeds in the slab.
CEILING_HEIGHT_M = 2.6  # matches settings.default_wall_height_m below
_CEILING_GAP_M = 0.05
# A light mounted at/above this height counts as a ceiling fixture → downward panel.
_CEILING_MOUNT_MIN_M = 1.8

# Room-level softbox proxies. Infinigen fixtures are often small/high-energy,
# which is exactly the high-variance case for glossy measured materials. Keep
# those fixtures, but add sparse broad ceiling panels as render fill. The panels
# should behave like a small number of practical ceiling luminaires, not a dense
# luminous sky grid.
SOFTBOX_TARGET_COVERAGE = 0.12
SOFTBOX_MIN_SIZE_M = 0.8
SOFTBOX_MAX_SIZE_M = 2.2
SOFTBOX_FILL_RADIANCE = 3.0
SOFTBOX_PRIMARY_RADIANCE = 4.5


def _conserve_power(radiance: list[float]) -> list[float]:
    """Scale radiance down by the emitter-area increase (constant luminous power)."""
    return [round(r / _LIGHT_AREA_FACTOR, 3) for r in radiance]


def _ceiling_panel_height(base_height_m: float) -> float:
    """Clamp a ceiling fixture just below the ceiling slab (no embedding)."""
    return round(min(float(base_height_m), CEILING_HEIGHT_M - _CEILING_GAP_M), 4)


def _softbox_count_for_room(width: float, depth: float) -> int:
    area = max(0.0, float(width) * float(depth))
    if area < 35.0:
        return 1
    if area < 65.0:
        return 2
    if area < 105.0:
        return 3
    return 4


def _softbox_positions(min_x: float, min_y: float, width: float, depth: float, count: int) -> list[tuple[float, float]]:
    cx = min_x + width * 0.5
    cy = min_y + depth * 0.5
    if count <= 1:
        return [(cx, cy)]
    if count == 2:
        if width >= depth:
            return [(min_x + width / 3.0, cy), (min_x + width * 2.0 / 3.0, cy)]
        return [(cx, min_y + depth / 3.0), (cx, min_y + depth * 2.0 / 3.0)]
    if count == 3:
        if width >= depth * 1.45:
            return [(min_x + width * f, cy) for f in (0.25, 0.50, 0.75)]
        if depth >= width * 1.45:
            return [(cx, min_y + depth * f) for f in (0.25, 0.50, 0.75)]
        return [
            (min_x + width * 0.30, min_y + depth * 0.35),
            (min_x + width * 0.70, min_y + depth * 0.35),
            (min_x + width * 0.50, min_y + depth * 0.68),
        ]
    return [
        (min_x + width * 0.33, min_y + depth * 0.33),
        (min_x + width * 0.67, min_y + depth * 0.33),
        (min_x + width * 0.33, min_y + depth * 0.67),
        (min_x + width * 0.67, min_y + depth * 0.67),
    ]


def _room_softbox_specs(aabb: list[float], *, strong_fill: bool) -> list[dict]:
    """Return broad, weak ceiling-panel specs for one room floor AABB."""
    min_x, min_y, max_x, max_y = [float(v) for v in aabb]
    width = max(0.1, max_x - min_x)
    depth = max(0.1, max_y - min_y)
    count = _softbox_count_for_room(width, depth)
    target_panel_area = width * depth * SOFTBOX_TARGET_COVERAGE / max(count, 1)
    target_side = math.sqrt(max(target_panel_area, SOFTBOX_MIN_SIZE_M * SOFTBOX_MIN_SIZE_M))
    panel_x = min(SOFTBOX_MAX_SIZE_M, max(SOFTBOX_MIN_SIZE_M, target_side))
    panel_y = min(SOFTBOX_MAX_SIZE_M, max(SOFTBOX_MIN_SIZE_M, target_panel_area / max(panel_x, 1e-6)))
    panel_x = min(panel_x, max(0.35, width * 0.80))
    panel_y = min(panel_y, max(0.35, depth * 0.80))
    radiance = SOFTBOX_PRIMARY_RADIANCE if strong_fill else SOFTBOX_FILL_RADIANCE
    specs: list[dict] = []
    for x, y in _softbox_positions(min_x, min_y, width, depth, count):
        specs.append({
            "center": [round(x, 4), round(y, 4)],
            "size_m": [round(panel_x, 4), 0.04, round(panel_y, 4)],
            "radiance": [round(radiance, 3)] * 3,
        })
    return specs


# Structure subtypes that must NOT carve the traversability grid (their AABB is
# the whole room). Furniture carves; walls/floor/ceiling do not.
NO_CARVE_KINDS = {"structure", "window"}

# Infinigen keeps room-shell prototypes in this asset-library collection. They
# are authoring templates centered near the Blender origin, not placed scene
# instances. Importing them produces one large room-sized box per template,
# all stacked at the same normalized map corner.
_ROOM_EXTERIOR_PROTOTYPE_COLLECTION = "unique_assets:room_exterior"

# Infinigen's NatureShelfTrinkets assets are sometimes sculpt-resolution meshes
# even though their placed extent is only a few centimetres.  They are neither
# navigation geometry nor optical-evaluation targets, and one apartment seed can
# spend most of its triangle budget on them.  Drop only the pathological corner:
# shelf-decoration semantics, <=15 cm world extent, and >=250k triangles.  The
# narrow factory/semantic guard deliberately keeps jars, plants, landmarks and
# structural meshes even when they happen to be small.
_TINY_HIGHPOLY_MAX_EXTENT_M = 0.15
_TINY_HIGHPOLY_MIN_TRIANGLES = 250_000
_TINY_HIGHPOLY_FACTORIES = frozenset({"NatureShelfTrinketsFactory"})


def _is_room_exterior_prototype(unit: dict) -> bool:
    return any(
        str(collection).strip().lower() == _ROOM_EXTERIOR_PROTOTYPE_COLLECTION
        for collection in (unit.get("collections") or [])
    )


def _is_tiny_highpoly_decoration(unit: dict) -> bool:
    dimensions = unit.get("dimensions") or unit.get("place_size_m") or []
    try:
        max_extent = max(float(value) for value in dimensions)
        triangles = int(unit.get("triangles") or 0)
    except (TypeError, ValueError):
        return False
    return (
        str(unit.get("factory") or "") in _TINY_HIGHPOLY_FACTORIES
        and str(unit.get("semantic_type") or "") == "shelf"
        and max_extent <= _TINY_HIGHPOLY_MAX_EXTENT_M
        and triangles >= _TINY_HIGHPOLY_MIN_TRIANGLES
    )


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
      metal_*-> roughconductor analytic fallback plus a measured_polarized candidate
                recorded for render-time opt-in scopes
      diffuse-> pplastic with baked albedo (polarization-aware analytic fallback)
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
                   "capabilities": {"rgb": True, "polarization": True}}
    elif oc == "mirror":
        binding = {"kind": "preset", "bsdf_strategy": "conductor",
                   "base_color_factor": base, "roughness": rough, "metallic": metallic,
                   "capabilities": {"rgb": True, "polarization": True}}
    elif oc in _METAL_MEASURED_ID:
        mid = _METAL_MEASURED_ID[oc]
        # Source XML stays analytic/polarimetric by default. The measured pBRDF
        # remains available as an opt-in render-time candidate via the policy sidecar.
        binding = {"kind": "preset", "bsdf_strategy": "roughconductor",
                   "base_color_factor": base, "roughness": rough, "metallic": metallic,
                   "capabilities": {"rgb": True, "polarization": True},
                   "analytic_fallback": {
                       "kind": "preset", "bsdf_strategy": "roughconductor",
                       "base_color_factor": base, "roughness": rough, "metallic": metallic,
                       "capabilities": {"rgb": True, "polarization": True},
                   },
                   "measured_candidate": {
                       "kind": "hpbrdf_2025", "dataset_id": "hpbrdf_2025", "material_id": mid,
                       "bsdf_strategy": "measured_polarized",
                       "channels_dir": f"data/hpbrdf_2025/channels/{mid}",
                       "base_color_factor": base, "roughness": rough, "metallic": metallic,
                       "capabilities": {"rgb": True, "polarization": True},
                   },
                   "measured_role": "anchor"}
        if images and images[0].get("filepath"):
            binding["base_color_texture_ref"] = images[0]["filepath"]
            binding["analytic_fallback"]["base_color_texture_ref"] = images[0]["filepath"]
            binding["measured_candidate"]["base_color_texture_ref"] = images[0]["filepath"]
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

    # Carry optical_class into the render binding so the daemon can inject
    # per-material IOR / metal eta-k (ROBOMITUBA_BSDF_MODE=injected) without
    # re-deriving from the material name. (Older scenes lack this; the daemon
    # falls back to deriving from the material_id/shader name.)
    binding["optical_class"] = oc
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


# Thin / flat furniture the robot can drive over (rugs, carpets, mats, doormats,
# towels). Detected by factory/semantic name keyword OR by a tiny world-AABB
# height. Without this exemption the graph builder carves out rug footprints and
# leaves a node-shaped hole the user fills in manually every time.
_TRAVERSABLE_OVERLAY_KEYWORDS = ("rug", "carpet", "mat", "doormat", "towel")
_TRAVERSABLE_OVERLAY_HEIGHT_M = 0.05

# Oversized-door drop. Infinigen door-leaf factories sometimes emit a leaf far larger
# than its frame/opening that sits across a passage (a real leaf footprint is thin,
# ~0.05-0.2m, by ~0.8-1.0m wide → ~0.15m²). Such a leaf is dropped at import so it
# neither renders as a wall-sized door nor breaks doorway portal detection. Detection
# is frame-RELATIVE: a leaf is oversized when its horizontal footprint is far larger
# than its nearest door frame (door_base_elements), which marks the true opening and
# is robust across door scales. Absolute thresholds are only a fallback when no frame
# is nearby. Frames are NEVER dropped — only door *leaf* factories.
_DOOR_LEAF_FACTORY_HINT = "doorfactory"
_DOOR_FRAME_COLLECTION_HINT = "door_base_elements"
_DOOR_FRAME_MATCH_RADIUS_M = 1.5     # leaf↔frame pairing distance
_DOOR_LEAF_THICKNESS_FACTOR = 3.0    # leaf min-horiz > frame min-horiz × this → oversized
_DOOR_LEAF_THICKNESS_MARGIN_M = 0.2
_DOOR_LEAF_AREA_FACTOR = 2.5         # leaf area > frame area × this → oversized
_DOOR_LEAF_MAX_THICKNESS_M = 0.4     # absolute fallback (no frame nearby)
_DOOR_LEAF_MAX_AREA_M2 = 0.9


def _door_footprint(unit: dict) -> tuple[float, float, float] | None:
    """(min_horiz, area, _) of a door unit's horizontal footprint, or None."""
    size = unit.get("place_size_m") or []
    if len(size) < 3:
        return None
    sx, sz = float(size[0]), float(size[2])  # size[1] is height
    return min(sx, sz), sx * sz, 0.0


def _is_door_leaf(unit: dict) -> bool:
    if unit.get("kind") != "door":
        return False
    name = str(unit.get("blender_name") or unit.get("factory") or "").lower()
    return _DOOR_LEAF_FACTORY_HINT in name


def _is_door_frame(unit: dict) -> bool:
    return unit.get("kind") == "door" and any(
        _DOOR_FRAME_COLLECTION_HINT in str(c) for c in (unit.get("collections") or []))


def _drop_oversized_doors(units: list[dict]) -> tuple[list[dict], int]:
    """Drop door leaves whose footprint dwarfs their nearest frame. Returns (kept, n)."""
    import math
    frames = []
    for u in units:
        if not _is_door_frame(u):
            continue
        c = u.get("place_center")
        fp = _door_footprint(u)
        if c and fp:
            frames.append((float(c[0]), float(c[1]), fp[0], fp[1]))  # x, y, min_horiz, area

    def _nearest_frame(cx, cy):
        best = None
        for fx, fy, fmin, farea in frames:
            d = math.hypot(fx - cx, fy - cy)
            if d <= _DOOR_FRAME_MATCH_RADIUS_M and (best is None or d < best[0]):
                best = (d, fmin, farea)
        return best

    kept, dropped = [], 0
    for u in units:
        if not _is_door_leaf(u):
            kept.append(u)
            continue
        fp = _door_footprint(u)
        c = u.get("place_center")
        if not fp:
            kept.append(u)
            continue
        leaf_min, leaf_area, _ = fp
        frame = _nearest_frame(float(c[0]), float(c[1])) if c else None
        if frame is not None:
            _, fmin, farea = frame
            oversized = (leaf_min > fmin * _DOOR_LEAF_THICKNESS_FACTOR + _DOOR_LEAF_THICKNESS_MARGIN_M
                         or (farea > 0 and leaf_area > farea * _DOOR_LEAF_AREA_FACTOR))
        else:  # no frame to compare against — fall back to absolute thresholds
            oversized = leaf_min > _DOOR_LEAF_MAX_THICKNESS_M or leaf_area > _DOOR_LEAF_MAX_AREA_M2
        if oversized:
            dropped += 1
        else:
            kept.append(u)
    return kept, dropped


def _is_traversable_overlay(unit: dict) -> bool:
    factory = (unit.get("factory") or "").lower()
    sem = (unit.get("semantic_type") or "").lower()
    if any(kw in factory or kw in sem for kw in _TRAVERSABLE_OVERLAY_KEYWORDS):
        return True
    size = unit.get("place_size_m") or []
    height_m = float(size[1]) if len(size) >= 2 else 0.0
    return 0.0 < height_m < _TRAVERSABLE_OVERLAY_HEIGHT_M


def _nav_flags(unit: dict) -> dict:
    kind = unit.get("kind")
    sem = unit.get("semantic_type")
    flags = {"blocks_navigation": False, "include_in_hazard_mask": False,
             "hazard_type": None, "instruction_candidate": False, "goal_candidate": False,
             "traversable_overlay": False}
    if kind == "furniture":
        if _is_traversable_overlay(unit):
            flags["traversable_overlay"] = True
        else:
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
    elif sem in {"glass_wall", "transparent_partition"}:
        # Structural modern-office panes are real mesh obstacles, unlike a
        # legacy optical-perturbation overlay.  Keep their transparent-obstacle
        # semantics while making them participate in traversability.
        flags["blocks_navigation"] = True
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


def _validate_glb_mesh_contract(path: Path) -> list[str]:
    issues: list[str] = []
    try:
        with path.open("rb") as fh:
            header = fh.read(12)
            if len(header) != 12:
                return ["truncated GLB header"]
            magic, version, total_length = struct.unpack("<4sII", header)
            if magic != b"glTF" or version != 2:
                return ["not a GLB v2 file"]
            chunk_header = fh.read(8)
            if len(chunk_header) != 8:
                return ["missing GLB JSON chunk"]
            chunk_length, chunk_type = struct.unpack("<II", chunk_header)
            if chunk_type != 0x4E4F534A:
                return ["first GLB chunk is not JSON"]
            document = json.loads(fh.read(chunk_length))
            binary = b""
            while fh.tell() < total_length:
                next_header = fh.read(8)
                if len(next_header) != 8:
                    break
                next_length, next_type = struct.unpack("<II", next_header)
                payload = fh.read(next_length)
                if next_type == 0x004E4942:
                    binary = payload
        if total_length != path.stat().st_size:
            issues.append("header length does not match file size")
        accessors = document.get("accessors") or []
        buffer_views = document.get("bufferViews") or []

        component_formats = {
            5120: "b", 5121: "B", 5122: "h", 5123: "H", 5125: "I", 5126: "f",
        }
        component_counts = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}

        def read_accessor(accessor_index: int, element_index: int):
            accessor = accessors[accessor_index]
            view_index = accessor.get("bufferView")
            if not (isinstance(view_index, int) and 0 <= view_index < len(buffer_views)):
                raise ValueError("accessor has no valid bufferView")
            view = buffer_views[view_index]
            fmt = component_formats.get(accessor.get("componentType"))
            count = component_counts.get(accessor.get("type"))
            if fmt is None or count is None:
                raise ValueError("unsupported accessor component/type")
            item_size = struct.calcsize("<" + fmt * count)
            stride = int(view.get("byteStride") or item_size)
            offset = int(view.get("byteOffset") or 0) + int(accessor.get("byteOffset") or 0) + element_index * stride
            if offset < 0 or offset + item_size > len(binary):
                raise ValueError("accessor reads outside GLB BIN chunk")
            return struct.unpack_from("<" + fmt * count, binary, offset)
        primitives = [
            primitive
            for mesh in document.get("meshes") or []
            for primitive in mesh.get("primitives") or []
        ]
        if not primitives:
            issues.append("GLB has no mesh primitives")
        for index, primitive in enumerate(primitives):
            attrs = primitive.get("attributes") or {}
            counts: dict[str, int] = {}
            for semantic in ("POSITION", "TEXCOORD_0"):
                accessor_index = attrs.get(semantic)
                if not (isinstance(accessor_index, int) and 0 <= accessor_index < len(accessors)):
                    issues.append(f"primitive {index} missing {semantic} accessor")
                    continue
                count = int(accessors[accessor_index].get("count") or 0)
                counts[semantic] = count
                if count <= 0:
                    issues.append(f"primitive {index} has empty {semantic}")
            if counts.get("POSITION") and counts.get("TEXCOORD_0") != counts["POSITION"]:
                issues.append(f"primitive {index} POSITION/TEXCOORD_0 count mismatch")
            indices = primitive.get("indices")
            if indices is not None and not (
                isinstance(indices, int) and 0 <= indices < len(accessors)
                and int(accessors[indices].get("count") or 0) > 0
            ):
                issues.append(f"primitive {index} has invalid/empty indices")
            if primitive.get("mode", 4) != 4:
                issues.append(f"primitive {index} is not TRIANGLES")
                continue
            uv_accessor = attrs.get("TEXCOORD_0")
            if not (isinstance(uv_accessor, int) and 0 <= uv_accessor < len(accessors)):
                continue
            try:
                if indices is None:
                    index_count = int(accessors[attrs["POSITION"]].get("count") or 0)
                else:
                    index_count = int(accessors[indices].get("count") or 0)
                triangle_count = index_count // 3
                step = max(1, triangle_count // 4000)
                nonzero_area = False
                for triangle_index in range(0, triangle_count, step):
                    if indices is None:
                        vertex_indices = (triangle_index * 3, triangle_index * 3 + 1, triangle_index * 3 + 2)
                    else:
                        vertex_indices = tuple(
                            int(read_accessor(indices, triangle_index * 3 + corner)[0])
                            for corner in range(3)
                        )
                    uv0, uv1, uv2 = (read_accessor(uv_accessor, vertex) for vertex in vertex_indices)
                    area2 = abs(
                        (uv1[0] - uv0[0]) * (uv2[1] - uv0[1])
                        - (uv1[1] - uv0[1]) * (uv2[0] - uv0[0])
                    )
                    if math.isfinite(area2) and area2 > 1e-10:
                        nonzero_area = True
                        break
                if not nonzero_area:
                    issues.append(f"primitive {index} has degenerate TEXCOORD_0 triangle area")
            except Exception as exc:  # noqa: BLE001
                issues.append(f"primitive {index} UV data invalid: {exc}")
    except Exception as exc:  # noqa: BLE001
        issues.append(f"cannot parse GLB: {exc}")
    return issues



def validate_infinigen_manifest(
    manifest: dict,
    manifest_dir: Path,
    *,
    allow_obj_fallback: bool = False,
    stage1_profile: str = "strict-pbr-v1",
) -> list[str]:
    """Validate the Stage-1 GLB/PBR contract."""
    actual_profile = str(manifest.get("stage1_profile") or "strict-pbr-v1")
    if actual_profile != stage1_profile:
        raise ValueError(
            f"Stage-1 profile mismatch: expected {stage1_profile!r}, got {actual_profile!r}"
        )
    bootstrap = stage1_profile == "ir-bootstrap-v1"
    if stage1_profile not in {"strict-pbr-v1", "strict-pbr-v2-slot-aware", "ir-bootstrap-v1"}:
        raise ValueError(f"unsupported Stage-1 profile: {stage1_profile!r}")
    issues: list[str] = []
    if int(manifest.get("export_contract_version") or 0) < 2:
        issues.append("manifest export_contract_version is not 2")
    if bootstrap and not isinstance(manifest.get("materials"), dict):
        issues.append("manifest materials provenance is missing")
    for index, unit in enumerate(manifest.get("units") or []):
        uid = str(unit.get("id") or unit.get("blender_name") or index)
        glb_ref = unit.get("mesh_glb")
        if not glb_ref:
            issues.append(f"{uid}: missing mesh_glb")
        else:
            glb_path = manifest_dir / str(glb_ref)
            if not glb_path.is_file():
                issues.append(f"{uid}: GLB does not exist: {glb_ref}")
            else:
                for glb_issue in _validate_glb_mesh_contract(glb_path):
                    issues.append(f"{uid}: {glb_issue}")
                expected_digest = str(unit.get("glb_sha256") or "")
                if not expected_digest:
                    issues.append(f"{uid}: missing GLB digest")
                else:
                    actual_digest = hashlib.sha256(glb_path.read_bytes()).hexdigest()
                    if actual_digest != expected_digest:
                        issues.append(f"{uid}: GLB digest mismatch")
        uv = unit.get("uv") if isinstance(unit.get("uv"), dict) else {}
        if not uv.get("valid"):
            issues.append(f"{uid}: missing or invalid UV")
        if not str(uv.get("layer") or "").strip():
            issues.append(f"{uid}: missing UV layer")
        if bootstrap:
            if not str(unit.get("blender_name") or "").strip():
                issues.append(f"{uid}: missing Blender object provenance")
            if not isinstance(unit.get("materials"), list):
                issues.append(f"{uid}: missing material-name provenance")
            slots = unit.get("material_slots")
            if not isinstance(slots, list):
                issues.append(f"{uid}: missing material-slot provenance")
            elif any(not isinstance(slot, dict) or not str(slot.get("name") or "").strip() for slot in slots):
                issues.append(f"{uid}: invalid material-slot provenance")
            continue
        pbr = unit.get("pbr") if isinstance(unit.get("pbr"), dict) else {}
        if pbr.get("status") != "ok":
            issues.append(f"{uid}: unresolved PBR contract")
        if not pbr.get("self_contained_glb"):
            issues.append(f"{uid}: GLB is not declared self-contained")
        channels = pbr.get("channels") if isinstance(pbr.get("channels"), dict) else {}
        for channel in ("base_color", "roughness", "metallic", "normal"):
            rec = channels.get(channel) if isinstance(channels.get(channel), dict) else {}
            mode = rec.get("mode")
            if mode not in {"texture", "constant", "not_applicable"}:
                issues.append(f"{uid}: unresolved PBR channel {channel}")
            elif mode == "texture":
                ref = str(rec.get("ref") or "")
                resolution = rec.get("resolution")
                if not ref or not (manifest_dir / ref).is_file():
                    issues.append(f"{uid}: missing PBR texture {channel}: {ref}")
                if rec.get("colorspace") not in {"srgb", "raw"}:
                    issues.append(f"{uid}: invalid colorspace for {channel}")
                if not (isinstance(resolution, list) and len(resolution) == 2 and all(int(v) > 0 for v in resolution)):
                    issues.append(f"{uid}: invalid texture resolution for {channel}")
                if rec.get("source") == "linked":
                    bake_validation = rec.get("bake_validation")
                    if not isinstance(bake_validation, dict):
                        issues.append(f"{uid}: missing bake validation for linked {channel}")
                    elif bake_validation.get("result") != "spatial":
                        issues.append(
                            f"{uid}: linked {channel} bake validation is "
                            f"{bake_validation.get('result', 'unknown')}"
                        )
            elif mode == "constant":
                if rec.get("value") is None:
                    issues.append(f"{uid}: missing constant value for {channel}")
                if rec.get("colorspace") not in {"srgb", "raw"}:
                    issues.append(f"{uid}: invalid colorspace for {channel}")
    if issues and not allow_obj_fallback:
        detail = "\n  - ".join(issues[:40])
        extra = f"\n  ... and {len(issues) - 40} more" if len(issues) > 40 else ""
        raise ValueError(
            "strict Infinigen GLB/PBR manifest validation failed:\n  - "
            + detail + extra
            + "\nRe-export with the current pipeline or pass --allow-obj-fallback explicitly."
        )
    return issues

def build_authoring_map(manifest: dict, scene_id: str, import_rel: str,
                        *, keep_empty_rooms: bool = False, room_override: str | None = None,
                        normalize_origin: bool = True, origin_margin: float = 0.5,
                        fill_missing_lights: bool = True, allow_obj_fallback: bool = False) -> dict:
    all_units = manifest.get("units") or []
    mats_in = manifest.get("materials") or {}

    # GLB is authoritative. OBJ face inspection is retained only for an explicitly
    # degraded legacy import.
    def _has_render_geometry(unit: dict) -> bool:
        glb_ref = unit.get("mesh_glb")
        if glb_ref and (REPO_ROOT / import_rel / str(glb_ref)).is_file():
            return True
        obj_ref = unit.get("mesh_obj")
        return bool(
            allow_obj_fallback and obj_ref
            and _obj_has_faces(REPO_ROOT / import_rel / str(obj_ref))
        )

    units = [u for u in all_units if _has_render_geometry(u)]
    skipped = len(all_units) - len(units)

    room_exterior_prototypes = [u for u in units if _is_room_exterior_prototype(u)]
    if room_exterior_prototypes:
        units = [u for u in units if not _is_room_exterior_prototype(u)]
        print(f"[import] dropped {len(room_exterior_prototypes)} room-exterior prototype(s)")

    tiny_highpoly_decorations = [u for u in units if _is_tiny_highpoly_decoration(u)]
    if tiny_highpoly_decorations:
        units = [u for u in units if not _is_tiny_highpoly_decoration(u)]
        dropped_triangles = sum(int(u.get("triangles") or 0) for u in tiny_highpoly_decorations)
        print(
            f"[import] dropped {len(tiny_highpoly_decorations)} tiny high-poly "
            f"decoration(s), {dropped_triangles:,} triangles"
        )

    # Drop oversized door leaves (much larger than their nearest frame) that block a
    # passage. Removing them keeps the scene nav-clean (no wall-sized door mesh) and
    # lets doorway portal detection resolve so the rooms stay connected.
    units, _n_dropped_doors = _drop_oversized_doors(units)
    if _n_dropped_doors:
        print(f"[import] dropped {_n_dropped_doors} oversized door(s)")

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
        "render_binding": {"kind": "preset", "bsdf_strategy": "pplastic",
                           "base_color_factor": [0.6, 0.6, 0.6],
                           "capabilities": {"rgb": True, "polarization": True}},
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
        glb_ref = u.get("mesh_glb")
        if glb_ref and (REPO_ROOT / import_rel / str(glb_ref)).is_file():
            source_ref = f"{import_rel}/{glb_ref}"
            geometry_source = "glb"
        elif allow_obj_fallback and u.get("mesh_obj"):
            source_ref = f"{import_rel}/{u['mesh_obj']}"
            geometry_source = "obj_fallback"
        else:
            raise ValueError(f"{u.get('id')}: no valid GLB geometry")
        # authoring yaw MUST be 0 here. Stage 1 (blender_export_scene.py) exports each
        # unit's OBJ origin-local but with the world ORIENTATION BAKED INTO THE MESH
        # vertices, and reports size_m as the rotated WORLD AABB. Both consumers of
        # geometry.yaw_deg — the webui editor (MapEditor3D, group.rotation.y) and the
        # render path (usd_exporter._set_xform_translate_rotate) — apply it on top of
        # that already-rotated mesh, so any nonzero value DOUBLE-rotates the object.
        # (deb1a8c set yaw_deg=manifest yaw to tighten nav carving; that's wrong for a
        # baked mesh and is moot anyway because Infinigen furniture sits at right-angle
        # yaw (±90/±180) where the world AABB is already a tight footprint.) Keep the
        # real Blender yaw in metadata for reference / future un-baked exports.
        manifest_yaw = float(u.get("yaw_deg") or 0.0)
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
                "source_collections": list(u.get("collections") or []),
                "infinigen_yaw_deg": round(manifest_yaw, 3),
                "glb_ref": (f"{import_rel}/{u['mesh_glb']}" if u.get("mesh_glb") else None),
                "fallback_obj_ref": (f"{import_rel}/{u['mesh_obj']}" if u.get("mesh_obj") else None),
                "geometry_source": geometry_source,
                "pbr": u.get("pbr"),
                "uv": u.get("uv"),
                "world_bbox_min": u.get("world_bbox_min"),
                "world_bbox_max": u.get("world_bbox_max"),
                "source_custom_properties": dict(u.get("source_custom_properties") or {}),
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
        # Map Blender watts to a modest area-emitter radiance (heuristic, tunable),
        # then conserve power across the wider LIGHT_SIZE_M panel to cut firefly noise.
        rad = _conserve_power([
            max(0.0, col[0]) * min(40.0, energy / 10.0 + 4.0),
            max(0.0, col[1]) * min(40.0, energy / 10.0 + 4.0),
            max(0.0, col[2]) * min(40.0, energy / 10.0 + 4.0),
        ])
        raw_h = float(lt.get("place_base_height_m", 2.4))
        is_ceiling = raw_h >= _CEILING_MOUNT_MIN_M
        geometry = {"type": "point", "center": [round(c[0], 4), round(c[1], 4)],
                    "yaw_deg": 0.0, "size_m": list(LIGHT_SIZE_M),
                    "base_height_m": _ceiling_panel_height(raw_h) if is_ceiling else round(raw_h, 4)}
        obj = {
            "id": _san(f"light_{i}_{lt.get('name','')}"),
            "type": "landmark",
            "label": f"light:{lt.get('name','')}"[:64],
            "placement": "point",
            "geometry": geometry,
            "material": DEFAULT_MAT,
            "navigation": {"blocks_navigation": False},
            "is_emitter": True,
            "emitter_radiance": rad,
            "emitter_intensity": 1.0,
            "metadata": {"infinigen_light": True, "blender_type": lt.get("type")},
        }
        if is_ceiling:
            # Downward-facing flat panel (renderer reads this) — even, low-variance fill.
            obj["emitter_shape"] = "ceiling_panel"
        objects.append(obj)

    # Synthesize broad ceiling softboxes for finished rooms.
    # Infinigen's constraint solver is best-effort: the "1-4 ceiling lights per
    # room" rule in home.py is minimized-violation, not guaranteed, so some seeds
    # light only a couple of rooms (e.g. bedroom/bathroom) and leave living/
    # kitchen/dining with zero ceiling emitters. Even when fixtures exist, they
    # are small/high-variance; broad weak proxies give the renderer a stable
    # sampled light source per room. Runs in the pre vertical-normalize frame so
    # the dz shift below applies uniformly.
    if fill_missing_lights and kept_rooms:
        CEIL_Z_MIN = 2.0  # an emitter above this counts as a room's ceiling light
        ceil_lights = [o for o in objects
                       if o.get("is_emitter")
                       and float(o["geometry"].get("base_height_m", 0.0)) >= CEIL_Z_MIN]
        if ceil_lights:
            zs = sorted(float(o["geometry"]["base_height_m"]) for o in ceil_lights)
            ceil_z = zs[len(zs) // 2]
            rads = sorted(float(o["emitter_radiance"][0]) for o in ceil_lights)
            synth_rad = [rads[len(rads) // 2]] * 3
        else:
            ceil_z = 2.6
            synth_rad = [SOFTBOX_PRIMARY_RADIANCE] * 3
        synth = 0
        for rk in sorted(kept_rooms):
            a = room_floor.get(rk)
            if not a:
                continue
            has_room_ceiling_light = any(
                _xy_in(a, e["geometry"]["center"][0], e["geometry"]["center"][1])
                for e in ceil_lights
            )
            for si, spec in enumerate(_room_softbox_specs(a, strong_fill=not has_room_ceiling_light)):
                rad = spec["radiance"] if has_room_ceiling_light else [round(x, 3) for x in synth_rad]
                objects.append({
                    "id": _san(f"light_softbox_{rk}_{si:02d}"),
                    "type": "landmark",
                    "label": f"light:softbox:{rk}:{si}"[:64],
                    "placement": "point",
                    "geometry": {"type": "point", "center": spec["center"],
                                 "yaw_deg": 0.0, "size_m": spec["size_m"],
                                 "base_height_m": _ceiling_panel_height(ceil_z)},
                    "material": DEFAULT_MAT,
                    "navigation": {"blocks_navigation": False},
                    "is_emitter": True,
                    "emitter_shape": "ceiling_panel",
                    "emitter_radiance": rad,
                    "emitter_intensity": 1.0,
                    "metadata": {
                        "infinigen_light": True,
                        "synthesized": True,
                        "softbox_proxy": True,
                        "room": rk,
                        "room_had_ceiling_light": has_room_ceiling_light,
                    },
                })
                synth += 1
        if synth:
            print(f"[import] synthesized {synth} room softbox light(s)")

    # Traversable regions — one per finished room floor, NOT the outer AABB of
    # all floors unioned. Using the outer AABB makes outdoor space (between two
    # L-shaped rooms, or beyond the apartment perimeter) traversable, which the
    # graph builder then samples and the user has to delete manually. Emitting
    # each room as its own rectangle makes the region OR-mask the true union of
    # interior floors only, so outdoor cells are never candidates. Multi-room
    # apartments stay covered (each room is a separate traversable region).
    inset = 0.25
    if floor_bounds:
        regions = []
        for i, b in enumerate(floor_bounds):
            mnx, mny, mxx, mxy = float(b[0]), float(b[1]), float(b[2]), float(b[3])
            # Drop degenerate floors (rare — extruded line, missing extent).
            if mxx - mnx <= 2 * inset or mxy - mny <= 2 * inset:
                continue
            regions.append({
                "id": f"traversable_room_{i:02d}",
                "type": "traversable",
                "label": f"Room {i + 1} floor",
                "placement": "rectangle",
                "geometry": {"type": "rectangle", "bounds": [
                    round(mnx + inset, 3), round(mny + inset, 3),
                    round(mxx - inset, 3), round(mxy - inset, 3),
                ]},
                "floor_material_id": DEFAULT_MAT,
            })
        # Outer bounds for the goal rectangle + the origin normalization that
        # follows. Still computed from the floor union, but only used as a
        # reference frame — not as a traversable region.
        min_x = min(b[0] for b in floor_bounds); min_y = min(b[1] for b in floor_bounds)
        max_x = max(b[2] for b in floor_bounds); max_y = max(b[3] for b in floor_bounds)
    else:
        cs = [o["geometry"]["center"] for o in objects]
        min_x = min(c[0] for c in cs); max_x = max(c[0] for c in cs)
        min_y = min(c[1] for c in cs); max_y = max(c[1] for c in cs)
        trav = [round(min_x + inset, 3), round(min_y + inset, 3),
                round(max_x - inset, 3), round(max_y - inset, 3)]
        regions = [{
            "id": "traversable_main", "type": "traversable", "label": "Apartment floor",
            "placement": "rectangle", "geometry": {"type": "rectangle", "bounds": trav},
            "floor_material_id": DEFAULT_MAT,
        }]
    # Goal: a small rectangle near one corner of the outer reference frame.
    gx0 = round(max_x - 1.2, 3); gy0 = round(max_y - 1.2, 3)
    regions.append({
        "id": "goal_corner", "type": "goal", "label": "Goal",
        "placement": "rectangle",
        "geometry": {"type": "rectangle", "bounds": [
            gx0, gy0, round(max_x - inset, 3), round(max_y - inset, 3),
        ]},
    })

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
        # Constant ambient is a zero-variance fill that lifts dark corners (no
        # firefly cost), and ceiling_fill_gain turns the sealed ceiling into a
        # large downward area light (cheap to importance-sample) — both cut noise
        # in light-starved zones at the same spp. See render_daemon's
        # _ceiling_skylight_radiance / _append_environment_xml.
        "environment": {"mode": "constant", "radiance": [0.55, 0.57, 0.6], "intensity": 1.0,
                        "ceiling_skylight": True, "ceiling_fill_gain": 1.6,
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
                     "dropped_room_exterior_prototypes": len(room_exterior_prototypes),
                     "dropped_tiny_highpoly_decorations": len(tiny_highpoly_decorations),
                     "dropped_tiny_highpoly_triangles": sum(
                         int(u.get("triangles") or 0) for u in tiny_highpoly_decorations
                     ),
                     "tiny_highpoly_filter": {
                         "max_extent_m": _TINY_HIGHPOLY_MAX_EXTENT_M,
                         "min_triangles": _TINY_HIGHPOLY_MIN_TRIANGLES,
                         "factories": sorted(_TINY_HIGHPOLY_FACTORIES),
                     },
                     "kept_rooms": sorted(kept_rooms), "dropped_rooms": dropped_rooms,
                     "origin_offset": origin_offset},
    }


_PRESERVED_ROOT_FILES = {
    "nav_graph.json", "viewpoint_graph.json", "traversable_grid.npy",
    "traversable_grid.npy.json", "graph_edit_history.jsonl",
    "optical_perturbation.json",
}

def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

def _preserved_scene_hashes(scene_dir: Path) -> dict:
    # Root navigation artifacts are small enough for byte hashes. Observation trees
    # can exceed 10 GB; the importer never opens them for writing, so snapshot their
    # complete path/size/mtime/inode state in one constant-memory digest.  Pilot
    # acceptance may additionally compare an offline byte digest before and after.
    root_hashes = {
        name: _sha256_path(scene_dir / name)
        for name in sorted(_PRESERVED_ROOT_FILES)
        if (scene_dir / name).is_file()
    }
    observation_state = hashlib.sha256()
    observation_count = 0
    for dirname in ("observations", "observations_perturbed"):
        root = scene_dir / dirname
        if not root.is_dir():
            continue
        for path in sorted(p for p in root.rglob("*") if p.is_file()):
            stat = path.stat()
            record = (
                f"{path.relative_to(scene_dir).as_posix()}\0{stat.st_size}\0"
                f"{stat.st_mtime_ns}\0{stat.st_ino}\n"
            )
            observation_state.update(record.encode("utf-8"))
            observation_count += 1
    return {
        "root_byte_hashes": root_hashes,
        "observation_state_digest": observation_state.hexdigest(),
        "observation_file_count": observation_count,
    }

def _assert_stable_object_ids(existing: dict, candidate: dict) -> None:
    def mapping(payload):
        result = {}
        for obj in payload.get("objects") or []:
            meta = obj.get("metadata") if isinstance(obj.get("metadata"), dict) else {}
            name = str(meta.get("blender_name") or "")
            if meta.get("infinigen") and name:
                result[name] = str(obj.get("id") or "")
        return result
    old, new = mapping(existing), mapping(candidate)
    missing = sorted(set(old) - set(new))
    churn = sorted(name for name in set(old) & set(new) if old[name] != new[name])
    if missing or churn:
        details = []
        if missing:
            details.append(f"missing existing objects={missing[:12]}")
        if churn:
            details.append(f"changed object ids={[(name, old[name], new[name]) for name in churn[:12]]}")
        raise ValueError("object-ID stability check failed; refusing scene promotion: " + "; ".join(details))

def _snapshot_generated_scene_files(scene_dir: Path, snapshot_root: Path) -> Path | None:
    if not scene_dir.is_dir():
        return None
    snapshot_dir = snapshot_root / (time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + f"-{time.time_ns()}")
    snapshot_dir.mkdir(parents=True, exist_ok=False)
    for path in sorted(scene_dir.iterdir()):
        if path.is_file() and path.name not in _PRESERVED_ROOT_FILES:
            shutil.copy2(path, snapshot_dir / path.name)
    return snapshot_dir


def _repo_relative_import_root(manifest_dir: Path, scene_id: str) -> str:
    """Return a stable package-relative alias for a Stage-1 artifact root.

    OpticalNav ``source_ref`` values are deliberately package-relative.  IR
    geometry builds, however, live on the dataset work volume (normally
    ``/bean``), outside ``REPO_ROOT``.  Keep the package contract intact by
    placing a small, deterministic symlink in the ignored import tree instead
    of copying the authoritative GLBs and texture atlases back into the repo.
    """
    root = manifest_dir.resolve()
    try:
        return root.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        pass

    digest = hashlib.sha256(str(root).encode("utf-8")).hexdigest()[:16]
    alias = REPO_ROOT / "out" / "infinigen_imports" / "_external" / f"{_san(scene_id)}-{digest}"
    alias.parent.mkdir(parents=True, exist_ok=True)
    if alias.is_symlink():
        if alias.resolve() != root:
            raise RuntimeError(f"external import alias points elsewhere: {alias}")
    elif alias.exists():
        raise RuntimeError(f"external import alias is not a symlink: {alias}")
    else:
        alias.symlink_to(root, target_is_directory=True)
    return alias.relative_to(REPO_ROOT).as_posix()


def _display_path(path: Path) -> str:
    """Use a concise repo-relative path when possible, otherwise an absolute path."""
    try:
        return path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return str(path)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--scene-id", default=None)
    ap.add_argument("--project-id", default="opticalnav-v0.2")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--validate-only", action="store_true",
                    help="Validate the Stage-1 GLB/PBR manifest and exit.")
    ap.add_argument("--stage1-profile", choices=("strict-pbr-v1", "ir-bootstrap-v1"),
                    default="strict-pbr-v1",
                    help="Expected Stage-1 contract; bootstrap keeps geometry/material provenance without atlases.")
    ap.add_argument("--allow-obj-fallback", action="store_true",
                    help="Permit legacy/incomplete manifests and audited OBJ geometry fallback.")
    ap.add_argument("--no-materialize", action="store_true")
    ap.add_argument("--allow-object-id-churn", action="store_true",
                    help="Allow replacing an existing scene when stable Infinigen object IDs disappear or change.")
    ap.add_argument("--keep-empty-rooms", action="store_true",
                    help="Keep all rooms, including unfurnished/unsolved shells.")
    ap.add_argument("--room", default=None,
                    help="Keep only this room key (e.g. 'dining-room_0/0').")
    ap.add_argument("--no-normalize-origin", action="store_true",
                    help="Keep raw Infinigen world coords instead of shifting the layout to the origin.")
    ap.add_argument("--optical-perturbation", nargs="?", const=0, type=int, default=None,
                    metavar="SEED",
                    help="After import, auto-place mirrors+glass as a toggleable optical "
                         "perturbation overlay (optional SEED). Glass walls need the viewpoint "
                         "graph; rerun `opticalnav perturbation build` after graph build for those.")
    ap.add_argument("--no-fill-missing-lights", action="store_true",
                    help="Do not synthesize ceiling lights for rooms Infinigen left unlit.")
    args = ap.parse_args()

    manifest_path = Path(args.manifest).resolve()
    manifest = json.loads(manifest_path.read_text())
    validation_issues = validate_infinigen_manifest(
        manifest, manifest_path.parent, allow_obj_fallback=args.allow_obj_fallback,
        stage1_profile=args.stage1_profile,
    )
    if args.validate_only:
        print(f"[import] manifest validation ok: {manifest_path}")
        if validation_issues:
            print(f"[import] degraded validation issues: {len(validation_issues)}")
        return
    scene_id = _scene_id_from_manifest(manifest_path, args.scene_id)
    # repo-relative import root (meshes live under here as <import_rel>/meshes/<id>.obj)
    import_rel = _repo_relative_import_root(manifest_path.parent, scene_id)

    am = build_authoring_map(manifest, scene_id, import_rel,
                             keep_empty_rooms=args.keep_empty_rooms, room_override=args.room,
                             normalize_origin=not args.no_normalize_origin,
                             fill_missing_lights=not args.no_fill_missing_lights,
                             allow_obj_fallback=args.allow_obj_fallback)
    md = am["metadata"]
    md["export_contract_version"] = int(manifest.get("export_contract_version") or 0)
    md["stage1_profile"] = str(manifest.get("stage1_profile") or "strict-pbr-v1")
    md["import_degraded"] = bool(validation_issues)
    md["manifest_validation_issues"] = validation_issues
    print(f"[import] scene_id={scene_id} objects={len(am['objects'])} materials={len(am['materials'])} "
          f"trav={am['regions'][0]['geometry']['bounds']} (skipped {md.get('skipped_degenerate', 0)} degenerate)")
    print(f"[import] kept_rooms={md.get('kept_rooms')} dropped_rooms={md.get('dropped_rooms')} "
          f"origin_offset={md.get('origin_offset')}")

    scene_dir = REPO_ROOT / "out" / "opticalnav" / args.project_id / "scenes" / scene_id
    existing_authoring = scene_dir / "authoring_map.json"
    if existing_authoring.is_file() and not args.allow_object_id_churn:
        _assert_stable_object_ids(json.loads(existing_authoring.read_text()), am)
    preserved_before = _preserved_scene_hashes(scene_dir) if scene_dir.is_dir() else {}
    snapshot_dir = _snapshot_generated_scene_files(
        scene_dir, manifest_path.parent / "promotion_snapshots" / scene_id,
    )
    if snapshot_dir:
        print(f"[import] promotion snapshot -> {_display_path(snapshot_dir)}")

    fixture_path = REPO_ROOT / "out" / "infinigen_imports" / f"{scene_id}__authoring_map.json"
    fixture_path.parent.mkdir(parents=True, exist_ok=True)
    fixture_path.write_text(json.dumps(am, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[import] wrote fixture {fixture_path.relative_to(REPO_ROOT)}")

    result = install_shared_office_sample(
        REPO_ROOT, project_id=args.project_id, scene_id=scene_id,
        fixture_path=fixture_path, force=args.force,
        materialize_render_scene=not args.no_materialize,
    )
    preserved_after = _preserved_scene_hashes(scene_dir) if preserved_before else {}
    if preserved_after != preserved_before:
        changed = sorted(set(preserved_before) ^ set(preserved_after) | {
            key for key in set(preserved_before) & set(preserved_after)
            if preserved_before[key] != preserved_after[key]
        })
        raise RuntimeError(
            "navigation artifact preservation check failed after promotion: "
            + ", ".join(changed[:40])
        )
    if preserved_before:
        print(f"[import] preserved navigation root bytes and observation state: "
              f"{preserved_before['observation_file_count']} observation files")
    print(f"[import] installed -> {scene_dir.relative_to(REPO_ROOT)}")
    if args.optical_perturbation is not None:
        from navigation_dataset.optical_perturbation import build_optical_perturbation
        pp = build_optical_perturbation(scene_dir, seed=int(args.optical_perturbation))
        m = pp["metadata"]
        print(f"[import] optical perturbation: mirrors={m['mirror_count']} "
              f"glass={m['glass_wall_count']} disabled_edges={m['disabled_edge_count']} "
              f"-> {(scene_dir / 'optical_perturbation.json').relative_to(REPO_ROOT)}")
    rx = scene_dir / "render_scene.xml"
    print(f"[import] render_scene.xml exists={rx.exists()} size={rx.stat().st_size if rx.exists() else 0}")
    print(f"[import] DONE result_keys={list(result.__dict__.keys()) if hasattr(result,'__dict__') else type(result)}")


if __name__ == "__main__":
    main()
