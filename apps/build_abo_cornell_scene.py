#!/usr/bin/env python3
"""Compose a Cornell-box scene of ABO objects for the HSSD IR render chain.

This writes exactly what `hssd_blender_ir` already consumes -- a scene manifest
plus a stage GLB -- so nothing downstream needs an ABO-specific branch:

    build_abo_cornell_scene.py            (here)
      -> blender_build_scene.py           places the GLB instances
      -> blender_prepare_hssd_ir.py       flash rig, fixture lights, quarantine
      -> blender_render_hssd_ir_sample.py RGB / passive+active NIR / ARMN GT

Why a box at all: the active-NIR flash falls off as 1/r^2, so the specular cue
the dataset exists to capture only survives near the surface.  The camera works
at 0.8-1.2 m (`pose_gates.MIN_MEDIAN_DISTANCE_M`), and the box is sized *from*
the objects so that a full orbit at the working radius stays inside the walls
-- a fixed room silently rejects most of the ring on wall margin instead.

Composition is deliberately hierarchical rather than a flat scatter.  ABO is a
furniture catalogue: the median asset is 1.03 m across and a quarter exceed
2 m, so at 1 m a sofa does not fit the frame and is not a subject.  Large
assets are therefore hosts -- they contribute a support surface and act as
backdrop -- while the props standing on them are what the camera anchors on.
That is what puts several materials, their interreflections and a shared
shadow into one frame.

Luminaires are placed as ordinary instances and additionally declared in an
ABO semantics CSV, which is how `lighting.py` finds them: it reads assets whose
`super_category` is "lighting" and places a point light inside each one's bbox
at the height its `main_category` archetype implies.

That point light is the *only* thing lighting an ABO lamp.  62% of the
catalogue's 540 luminaires carry an `emissiveTexture`, which looks like a
self-lit shade until the factor is read: `emissiveFactor` is [0, 0, 0] on all
7953 assets, and glTF multiplies the two, so the emitted radiance is exactly
zero everywhere.  ABO is therefore in the same position as HSSD -- whose
`_fixture_lights` exists precisely because "HSSD ships no emissive materials"
-- and the semantics CSV is not an optimisation but the whole mechanism.

Geometry is authored in glTF axes (Y-up, floor at y=0).  Blender's importer
maps +Y to +Z, so an object's footprint is (extent.x, extent.z) and its height
is extent.y; instance matrices in the manifest are Blender-space (Z-up).
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import random
import shutil
import struct
import sys
from pathlib import Path
from typing import Any, Iterable, Sequence

import numpy as np
from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[1]
for _source in ("modules/hssd_blender_ir/src", "modules/mitsuba_converter/src",
                "modules/robomituba_bridge/src"):
    _candidate = str(REPO_ROOT / _source)
    if _candidate not in sys.path:
        sys.path.insert(0, _candidate)

sys.path.insert(0, str(REPO_ROOT / "apps"))

from build_abo_object_index import read_gltf_json  # noqa: E402
from hssd_blender_ir.box_lighting import (PROFILE as BOX_LIGHTING_PROFILE,  # noqa: E402
                                          OPEN_ENVIRONMENTS, WALL_AZIMUTH_DEG,
                                          OPEN_PROFILE as OPEN_LIGHTING_PROFILE)
from hssd_blender_ir.compiler import SCHEMA as HSSD_SCENE_SCHEMA, _summary  # noqa: E402
from hssd_blender_ir.gltf import rewrite_glb, sha256  # noqa: E402
from hssd_blender_ir.lighting import FIXTURE_PLACEMENT, LIGHTING_SUPER_CATEGORY  # noqa: E402
from hssd_blender_ir.material_naming import material_marker  # noqa: E402
from hssd_blender_ir.pbr import classify_material  # noqa: E402

SCHEMA = "robomituba.abo_cornell_scene.v1"

#: Poly Haven CC0 skies, checksummed in
#: `configs/ir_lighting/illumination_diversity_v2.json`. Only an open ceiling
#: uses them; a closed box never reads this path.
HDRI_DIR = REPO_ROOT / "assets" / "ir_lighting_hdri"

#: The real spaces this corpus is meant to cover, each pinned to the material
#: families it is actually made of and to whether its shell is open.
#:
#: Without this the composer draws every role from the whole pool, and the pool
#: is not uniform: metal holds 11 of the 96 wall-role materials and marble 8, so
#: an untyped draw produces metal-leaning rooms most of the time and four
#: distinct environments almost never. A "type" here is exactly two things --
#: which families each role may draw from, and what is left out of the shell.
#:
#: The grass/plant environment that was fifth is absent on purpose: ABO has no
#: plant geometry. Its 182 PLANTER entries are empty pots and its single
#: ARTIFICIAL_PLANT is a hanging ceramic planter with a rope, so the type would
#: have been a dirt floor with nothing standing on it.
ENVIRONMENT_TYPES: dict[str, dict[str, Any]] = {
    "marble_hall": {
        "palette": {"floor": ("marble", "tile"), "wall": ("marble",),
                    "ceiling": ("concrete", "tile"), "massing": ("marble", "concrete", "tile"),
                    "accent": ("marble", "rock")},
        "open_ceiling": False, "open_walls": 0,
    },
    "parking_tower": {
        "palette": {"floor": ("metal", "concrete"), "wall": ("metal",),
                    "ceiling": ("metal", "concrete"), "massing": ("metal", "concrete"),
                    "accent": ("metal", "concrete")},
        "open_ceiling": False, "open_walls": 0,
    },
    "concrete_building": {
        "palette": {"floor": ("wood", "fabric"), "wall": ("concrete",),
                    "ceiling": ("concrete",), "massing": ("concrete", "brick"),
                    "accent": ("concrete", "brick", "wood")},
        "open_ceiling": False, "open_walls": 0,
    },
    "outdoor_street": {
        "palette": {"floor": ("rock", "tile", "concrete"), "wall": ("concrete", "brick", "rock"),
                    "ceiling": ("concrete",), "massing": ("concrete", "brick", "metal", "tile"),
                    "accent": ("concrete", "rock", "brick")},
        "open_ceiling": True, "open_walls": 1,
    },
}
#: v3: both accent walls draw from one wider pool and are required to differ;
#: the prop size cap rises to 0.75 of the near frame width. Neither changes
#: what a scene *is*, but scenes composed under v2 draw from smaller pools and
#: are not comparable on material or asset diversity.
#: v2: structural finishes are drawn from the union of a role's preferred
#: categories rather than the first non-empty one, and the texel gate is
#: evaluated at the distance walls are actually seen from. Under v1 those two
#: together left every wall and ceiling in the dataset a choice of two
#: materials. Scenes composed under v1 are not comparable and the queue's
#: policy check will flag them.
COMPOSER_VERSION = "abo-cornell-v3"

#: The camera band this dataset is composed for.  `pose_gates` rejects a frame
#: whose median depth is under 0.8 m; the far end is where a prop of the
#: permitted size still sits comfortably inside the frame.
WORKING_RADIUS_M = (0.8, 1.2)
#: Default optics: JAI FS-1600 (1/2.9", 1440x1080 at 3.45 um, so a
#: 4.968 x 3.726 mm active area) behind a 6 mm lens, read out at 720x540.
#: That is 44.98 deg horizontally -- materially tighter than the 63.4 deg the
#: renderer falls back on, and the composition limits below are derived from
#: it rather than assumed, because framing and texel density both scale with
#: it and guessing wrong silently mis-sizes every prop in the dataset.
DEFAULT_HFOV_DEG = 44.98
DEFAULT_FRAME_WIDTH_PX = 720
#: A prop may occupy this much of the frame width at the near end.  Past it
#: `pose_gates.MAX_DOMINANT_MATERIAL` starts rejecting the pose for being one
#: material wall-to-wall, which is the same judgement from the other side.
#: v3 raises this from 0.60. At 0.60 the prop pool was 380 assets and 100
#: scenes placed 1,600 props from it, so 234 assets appeared four times or
#: more; 0.75 gives 529. The cap is a framing limit, not a physical one -- a
#: 0.50 m prop is 75% of the frame at the near standoff and half of it at the
#: far end, and the pose gates reject a frame one material fills regardless.
PROP_FRAME_FRACTION = 0.75
#: Below this a prop is a cable adapter reading as a smudge, not a subject --
#: an unfiltered draw picked a 0.04 m MULTIPORT_HUB.  At 1.0 m and 45 deg a
#: 0.12 m object still spans ~104 px.
MIN_PROP_EXTENT_M = 0.12
#: TextureCan ships 2K maps; the real pixel size is read per material, and
#: this is only the fallback when an image header cannot be opened.
ASSUMED_TEXTURE_PX = 2048
#: A surface higher than this cannot be dressed and then viewed from the
#: working band without the camera looking steeply up at it, so a taller host
#: contributes a lower shelf instead of its lid.
MAX_SUPPORT_HEIGHT_M = 1.40
#: Two ABO sofas are authored ~100x oversize; nothing real exceeds this.
MAX_PLAUSIBLE_EXTENT_M = 4.0
#: The room is derived from its contents, so host size sets room size: letting
#: the capacity filter reach for a 4 m dining table produced a 6.4 x 7.5 m
#: room, which is not the box this dataset is named for.  A host this wide
#: lands the walls near 4 m, and props that then do not fit are reported.
MAX_HOST_EXTENT_M = 1.80
#: Clear floor between a host's footprint and the wall, so the camera ring fits.
WALL_CLEARANCE_M = 0.25
#: Cornell boxes are cubic-ish; a tall room also keeps ceiling fixtures in play.
MIN_CEILING_HEIGHT_M = 2.4
#: A support band must be at least this big before a prop may stand on it.
MIN_SUPPORT_AREA_M2 = 0.06
MIN_SUPPORT_SIDE_M = 0.25
#: Gap between props sharing a surface, so they read as separate objects.
PROP_GAP_M = 0.04
#: Categories an accent wall may draw from -- everything that reads as a
#: departure from the concrete/brick/tile a main wall wears. 38 materials in
#: the current registry against the 11 the v2 west accent could reach.
ACCENT_CATEGORIES = ("fabric", "wood", "marble", "rock", "metal")
#: Structural roles the box exposes to the TextureCan registry.
BOX_ROLES = ("floor", "ceiling", "wall_north", "wall_south", "wall_east", "wall_west")

#: NIR reflectance is a fourth channel that cannot be recovered from RGB, so it
#: has to be *assigned* from a physical material class rather than derived from
#: the visible albedo -- the failure `nir_reflectance` was written to avoid and
#: that the Blender path's `derived_pseudo_nir` still performs.  ABO can do
#: better than HSSD here for a specific reason: `surface_lexicon` records that
#: all 5,381 HSSD materials read `furniture`, so it has to guess a surface from
#: the product title, while ABO states a product type for every one of its
#: 7,953 models.  These are the classes of
#: `configs/datasets/class_band_reflectance_v1.json`.
NIR_CLASS_BY_PRODUCT_TYPE: dict[str, str] = {
    # Upholstery and textiles.
    "SOFA": "dyed_fabric", "OTTOMAN": "dyed_fabric", "PILLOW": "dyed_fabric",
    "RUG": "dyed_fabric", "FURNITURE_COVER": "dyed_fabric", "HEADBOARD": "dyed_fabric",
    "CURTAIN": "dyed_fabric", "MATTRESS": "dyed_fabric",
    # Case goods and seating: an ABO chair or table is overwhelmingly a wood or
    # wood-veneer body, and wood carries the strongest spatial transfer of any
    # dielectric here (alpha 0.55), so grain survives into the NIR map.
    "CHAIR": "wood", "TABLE": "wood", "DESK": "wood", "CABINET": "wood",
    "SHELF": "wood", "DRESSER": "wood", "BED": "wood", "BED_FRAME": "wood",
    "BENCH": "wood", "STOOL_SEATING": "wood", "NIGHTSTAND": "wood",
    "BOOKCASE": "wood", "TVSTAND": "wood",
    # Glazed ceramics: near-uniform at 854 nm, hence the low alpha in the prior.
    "VASE": "ceramic", "PLANTER": "ceramic", "BOWL": "ceramic", "DINNERWARE": "ceramic",
    # Ink on a substrate: the print is a visible-band pattern that largely
    # disappears in the NIR, which is exactly what a 0.10 alpha encodes.
    "WALL_ART": "printed_surface", "POSTER": "printed_surface",
    "HOME_MIRROR": "bare_metal",
    "ELECTRIC_FAN": "painted_plastic_dark",
    "MULTIPORT_HUB": "painted_plastic_dark", "ELECTRONIC_CABLE": "painted_plastic_dark",
    "SPORTING_GOODS": "unpainted_plastic",
    # Luminaires mix a metal or ceramic body with a fabric shade and ABO gives
    # them one material, so no class is right; the mid-range plastic prior is
    # the least wrong, and its `confidence` records that.
    "LAMP": "unpainted_plastic", "LIGHT_FIXTURE": "unpainted_plastic",
}
#: The box's own surfaces, keyed by the TextureCan registry's category.
NIR_CLASS_BY_TEXTURECAN_CATEGORY: dict[str, str] = {
    "wood": "wood", "concrete": "concrete", "brick": "stone", "rock": "stone",
    "marble": "stone", "tile": "ceramic", "fabric": "dyed_fabric", "metal": "bare_metal",
}
#: A material this metallic is a conductor whatever the catalogue calls it, and
#: a conductor's band behaviour is Fresnel, not a diffuse map.
METAL_CLASS_THRESHOLD = 0.5
NIR_PRIOR_SCHEMA = "robomituba.abo_nir_class_assignment.v1"
DEFAULT_NIR_CLASSES = REPO_ROOT / "configs/datasets/class_band_reflectance_v1.json"

_LUMINAIRE_TYPES = frozenset({"LAMP", "LIGHT_FIXTURE"})
#: Ordered: the first phrase that matches wins, so "floor lamp" is tested
#: before the bare "lamp" that every one of these titles contains.
_ARCHETYPE_PHRASES: tuple[tuple[str, str], ...] = (
    ("chandelier", "chandelier"),
    ("pendant", "pendant_lamp"),
    ("sconce", "wall_lamp"),
    ("wall lamp", "wall_lamp"),
    ("wall light", "wall_lamp"),
    ("flush mount", "ceiling_lamp"),
    ("ceiling", "ceiling_lamp"),
    ("floor lamp", "floor_lamp"),
    ("table lamp", "table_lamp"),
    ("desk lamp", "table_lamp"),
    ("bedside", "table_lamp"),
    ("nightstand lamp", "table_lamp"),
)


def frame_width_m(distance_m: float, hfov_deg: float) -> float:
    """How wide the frame is, in metres, at a given standoff."""
    return 2.0 * distance_m * math.tan(math.radians(hfov_deg) / 2.0)


def camera_limits(hfov_deg: float, width_px: int) -> dict[str, float]:
    """Composition limits implied by the optics, at the near end of the band.

    Both limits move with the lens, so they are computed rather than written
    down.  At the renderer's 63.4 deg fallback the coarsest TextureCan
    material out-resolves the screen and no finish gate is needed at all; at
    the JAI's 45 deg the same near-end standoff demands 1087 px/m and 41 of
    the registry's 100 materials fall short.  A constant would have been right
    for one of those and quietly wrong for the other.
    """
    near = frame_width_m(WORKING_RADIUS_M[0], hfov_deg)
    return {
        "hfov_deg": hfov_deg,
        "frame_width_near_m": near,
        "frame_width_far_m": frame_width_m(WORKING_RADIUS_M[1], hfov_deg),
        "max_prop_extent_m": near * PROP_FRAME_FRACTION,
        "min_texel_px_per_m": width_px / near,
    }


def stable_digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def _rng(seed: int, *parts: Any) -> random.Random:
    """Digest-derived stream, so adding one object cannot perturb another's draw."""
    key = "|".join([COMPOSER_VERSION, *(str(part) for part in parts), str(int(seed))])
    return random.Random(int(hashlib.sha256(key.encode("utf-8")).hexdigest()[:16], 16))


# ---------------------------------------------------------------- classification


def luminaire_archetype(record: dict[str, Any]) -> str:
    """Map an ABO luminaire onto a `FIXTURE_PLACEMENT` archetype.

    Title text resolves most of the catalogue but leaves 78% unmatched on its
    own; folding in `item_keywords` and falling back on the silhouette (a lamp
    taller than 1.2 m stands on the floor, a small one stands on a table) takes
    the unresolved share to 5%, which then lands on `DEFAULT_PLACEMENT`.
    """
    haystack = " ".join([record.get("name") or "", *(record.get("keywords") or [])]).lower()
    for phrase, archetype in _ARCHETYPE_PHRASES:
        if phrase in haystack:
            return archetype
    height = record["extent_m"][1]
    if height > 1.2:
        return "floor_lamp"
    if max(record["extent_m"]) <= 0.6:
        return "table_lamp"
    return "table_lamp" if height <= 0.8 else "floor_lamp"


def usable_support(record: dict[str, Any]) -> dict[str, Any] | None:
    """The highest dressable band on this asset, ignoring any above head height.

    Taking the topmost band unconditionally put props on the lid of a 1.81 m
    cabinet, where the working band can only see them by craning upward.  A
    tall host is still worth having -- it just contributes one of its lower
    shelves instead.
    """
    best = None
    for band in record.get("support_bands") or []:
        width = band["xz_hi"][0] - band["xz_lo"][0]
        depth = band["xz_hi"][1] - band["xz_lo"][1]
        if band["area_m2"] < MIN_SUPPORT_AREA_M2 or min(width, depth) < MIN_SUPPORT_SIDE_M:
            continue
        if band["height_m"] > MAX_SUPPORT_HEIGHT_M:
            continue
        if best is None or band["height_m"] > best["height_m"]:
            best = band
    return best


def _footprint(record: dict[str, Any]) -> tuple[float, float]:
    extent = record["extent_m"]
    return float(extent[0]), float(extent[2])


# ---------------------------------------------------------------- selection


def select_cast(objects: Sequence[dict[str, Any]], *, hosts: int, props: int,
                luminaires: int, seed: int, max_prop_extent_m: float) -> dict[str, Any]:
    """Draw the scene's hosts, props and luminaires with type diversity enforced.

    Without the per-type cap the draw returns six planters: ABO's small-object
    tail is dominated by PLANTER and VASE, so an unconstrained sample makes
    every frame look the same.
    """
    usable = [row for row in objects
              if "extent_m" in row and max(row["extent_m"]) <= MAX_PLAUSIBLE_EXTENT_M]

    host_pool = [row for row in usable
                 if usable_support(row) and max(row["extent_m"]) <= MAX_HOST_EXTENT_M]
    prop_pool = [row for row in usable
                 if MIN_PROP_EXTENT_M <= max(row["extent_m"]) <= max_prop_extent_m
                 and row["product_type"] not in _LUMINAIRE_TYPES
                 # Wall art hangs and pillows belong on seating; neither stands
                 # on a table, and together they are a fifth of the small tail.
                 and row["product_type"] not in {"WALL_ART", "PILLOW", "RUG"}]
    lamp_pool = [row for row in usable if row["product_type"] in _LUMINAIRE_TYPES]

    for name, pool, wanted in (("host", host_pool, hosts), ("prop", prop_pool, props),
                               ("luminaire", lamp_pool, luminaires)):
        if wanted and len(pool) < wanted:
            raise ValueError(f"only {len(pool)} {name} candidates available, {wanted} requested")

    def draw(pool: Sequence[dict[str, Any]], count: int, tag: str) -> list[dict[str, Any]]:
        if not count:
            return []
        rng = _rng(seed, tag)
        cap = max(1, math.ceil(count / 3))
        order = list(pool)
        rng.shuffle(order)
        chosen: list[dict[str, Any]] = []
        used: dict[str, int] = {}
        for row in order:
            kind = row["product_type"]
            if used.get(kind, 0) >= cap:
                continue
            chosen.append(row)
            used[kind] = used.get(kind, 0) + 1
            if len(chosen) == count:
                return chosen
        # The cap is a preference, never a reason to fail: top up if it bound.
        for row in order:
            if len(chosen) == count:
                break
            if row not in chosen:
                chosen.append(row)
        return chosen

    drawn_props = draw(prop_pool, props, "prop")

    # Hosts are chosen for the props they have to carry, not drawn blind: an
    # unconditional draw picked a 0.41 m cabinet whose lid took two of six
    # props and stranded the rest.  Shelf packing wastes roughly half a band,
    # hence the slack.
    needed = 1.7 * sum(_footprint(item)[0] * _footprint(item)[1] for item in drawn_props)
    per_host = needed / max(1, hosts)

    def band_area(row: dict[str, Any]) -> float:
        band = usable_support(row)
        return ((band["xz_hi"][0] - band["xz_lo"][0])
                * (band["xz_hi"][1] - band["xz_lo"][1])) if band else 0.0

    roomy = [row for row in host_pool if band_area(row) >= per_host]
    if len(roomy) < hosts:
        # Nothing in the catalogue is big enough for this prop count, so fall
        # back on the roomiest hosts rather than failing the scene outright.
        roomy = sorted(host_pool, key=band_area, reverse=True)[:max(hosts * 8, 24)]

    # The ceiling luminaire is drawn from the overhead archetypes only: a
    # floor lamp hung from the ceiling is not a fixture, it is a mistake.
    overhead = [row for row in lamp_pool
                if luminaire_archetype(row) in {"ceiling_lamp", "pendant_lamp", "chandelier"}
                and row["extent_m"][1] <= 0.9]
    ceiling_luminaire = draw(overhead, 1, "ceiling")[0] if overhead else None

    return {"hosts": draw(roomy, hosts, "host"),
            "props": drawn_props,
            "luminaires": draw(lamp_pool, luminaires, "luminaire"),
            "ceiling_luminaire": ceiling_luminaire}


# ---------------------------------------------------------------- placement


def _place_hosts(hosts: Sequence[dict[str, Any]], rng: random.Random) -> list[dict[str, Any]]:
    """Lay hosts along a line with clearance, centred on the origin.

    A line rather than a scatter: every host must be reachable by a camera
    orbit that does not pass through another host, and a row guarantees that
    without a visibility search the composer has no renderer to run.

    The gap is one working radius, not two.  Two private rings pushed a
    two-host scene out to 7.35 x 5.24 m, which is a hall rather than the box
    this dataset is named for; the camera stands *between* the hosts, so one
    radius of clear floor is what it actually needs.
    """
    gap = WORKING_RADIUS_M[0]
    widths = [_footprint(host)[0] for host in hosts]
    span = sum(widths) + gap * max(0, len(hosts) - 1)
    cursor = -span / 2.0
    placed = []
    for host, width in zip(hosts, widths):
        centre_x = cursor + width / 2.0
        cursor += width + gap
        placed.append({
            "record": host,
            "position": (centre_x, rng.uniform(-0.05, 0.05)),
            "yaw": rng.uniform(-math.pi, math.pi) if rng.random() < 0.5 else 0.0,
        })
    return placed


def _pack_on_surface(surface: dict[str, Any], props: Sequence[dict[str, Any]],
                     rng: random.Random) -> list[dict[str, Any]]:
    """Row-pack props across a support band, dropping those that will not fit.

    Returned offsets are in the host's own glTF frame (x, z), because that is
    the frame the band was measured in; the caller rotates them into the room.
    """
    x_low, z_low = surface["xz_lo"]
    x_high, z_high = surface["xz_hi"]
    x_limit = x_high - PROP_GAP_M
    z_limit = z_high - PROP_GAP_M

    # Shelf packing across the band's depth, not a single row along x: one row
    # left four of six props homeless on a 1 m table top that had the area for
    # all of them.  Deepest first, so a row's height is set before shallower
    # props fill it out.
    ordered = sorted(props, key=lambda item: -_footprint(item)[1])
    cursor_x = x_low + PROP_GAP_M
    cursor_z = z_low + PROP_GAP_M
    row_depth = 0.0
    seated = []
    for prop in ordered:
        width, depth = _footprint(prop)
        if cursor_x + width > x_limit:  # start a new row
            cursor_x = x_low + PROP_GAP_M
            cursor_z += row_depth + PROP_GAP_M
            row_depth = 0.0
        if cursor_z + depth > z_limit or cursor_x + width > x_limit:
            continue
        seated.append({"record": prop,
                       "local_xz": (cursor_x + width / 2.0, cursor_z + depth / 2.0),
                       "yaw": rng.uniform(-math.pi, math.pi)})
        cursor_x += width + PROP_GAP_M
        row_depth = max(row_depth, depth)
    return seated


def _to_room(local_xz: tuple[float, float], host_position: tuple[float, float],
             host_yaw: float) -> tuple[float, float]:
    """Carry a host-local glTF (x, z) offset into the room's Blender (x, y).

    Two conversions have to happen together and neither is optional.  The
    importer maps glTF +Z onto Blender -Y, so the sign of z flips; and the host
    carries its own yaw, so a prop measured in the host's frame has to turn
    with it.  Skipping the rotation leaves props hanging beside a turned table
    rather than on it.
    """
    local_x, local_y = local_xz[0], -local_xz[1]
    cos_a, sin_a = math.cos(host_yaw), math.sin(host_yaw)
    return (host_position[0] + local_x * cos_a - local_y * sin_a,
            host_position[1] + local_x * sin_a + local_y * cos_a)


def compose(cast: dict[str, Any], *, seed: int) -> dict[str, Any]:
    """Place every asset and derive the room that contains them."""
    rng = _rng(seed, "layout")
    hosts = _place_hosts(cast["hosts"], rng)

    props = list(cast["props"])
    placements: list[dict[str, Any]] = []
    # Share the props out rather than letting the first host pack until full:
    # one loaded table and one bare one is a worse scene than two dressed ones.
    share = math.ceil(len(props) / len(hosts)) if hosts and props else 0
    offers = [props[position * share:(position + 1) * share] if share else []
              for position in range(len(hosts))]

    def seat(host: dict[str, Any], offered: Sequence[dict[str, Any]]) -> None:
        record = host["record"]
        surface = usable_support(record)
        for item in _pack_on_surface(surface, offered, rng):
            props.remove(item["record"])
            placements.append({
                "record": item["record"],
                "role": "prop",
                "host_id": record["id"],
                "position": _to_room(item["local_xz"], host["position"], host["yaw"]),
                "seat_height": surface["height_m"],
                "yaw": item["yaw"] + host["yaw"],
            })

    for position, host in enumerate(hosts):
        seat(host, offers[position])
    # An even share is the preference, not the rule: a host whose band was too
    # small returns its offer, and rather than stranding those props they are
    # re-offered to every host before anything is given up on.
    for host in hosts:
        if not props:
            break
        seat(host, list(props))
    for host in hosts:
        surface = usable_support(host["record"])
        placements.append({"record": host["record"], "role": "support_host",
                           "position": host["position"], "seat_height": 0.0,
                           "yaw": host["yaw"], "support_height_m": surface["height_m"]})

    # Luminaires: table lamps join a surface, everything else stands on the
    # floor -- in its own row, clear of the hosts.  A fixed start coordinate
    # put a floor lamp inside a table, so the row is derived from how deep the
    # hosts actually reach and begins at the left edge of their span.
    host_reach = max((math.hypot(*_footprint(host["record"])) / 2.0 for host in hosts),
                     default=0.5)
    host_left = min((host["position"][0] - _footprint(host["record"])[0] / 2.0
                     for host in hosts), default=0.0)
    floor_row_y = host_reach + WORKING_RADIUS_M[0]
    floor_cursor = host_left
    for lamp in cast["luminaires"]:
        archetype = luminaire_archetype(lamp)
        seated = False
        if archetype == "table_lamp":
            for host in hosts:
                surface = usable_support(host["record"])
                width, _ = _footprint(lamp)
                if width <= (surface["xz_hi"][0] - surface["xz_lo"][0]) * 0.4:
                    local = (surface["xz_hi"][0] - width / 2.0 - PROP_GAP_M,
                             (surface["xz_lo"][1] + surface["xz_hi"][1]) / 2.0)
                    placements.append({
                        "record": lamp, "role": "luminaire", "archetype": archetype,
                        "host_id": host["record"]["id"],
                        "position": _to_room(local, host["position"], host["yaw"]),
                        "seat_height": surface["height_m"],
                        "yaw": rng.uniform(-math.pi, math.pi),
                    })
                    seated = True
                    break
        if not seated:
            width, _ = _footprint(lamp)
            placements.append({"record": lamp, "role": "luminaire", "archetype": archetype,
                               "position": (floor_cursor + width / 2.0, floor_row_y),
                               "seat_height": 0.0, "yaw": rng.uniform(-math.pi, math.pi)})
            floor_cursor += width + 0.6

    # A prop no surface would take is dropped, not scattered on the floor.
    # Floor-dumping placed a dresser and a placemat at fixed coordinates that
    # could sit inside a host, and an intersecting pair corrupts every GT
    # channel at once; an under-dressed scene is merely smaller.
    unplaced = [{"id": item["id"], "product_type": item["product_type"],
                 "extent_m": item["extent_m"]} for item in props]

    room = _derive_room(placements)

    # A Cornell box is a closed shell, so it has to carry its own ceiling
    # light.  `_window_portal_lights` finds no openings here and sun/sky reach
    # a windowless interior with zero radiance -- the pilot's RGB pass came
    # back at exactly 0.0 for this reason -- which leaves the fixture layer as
    # the only source.  Hanging one luminaire from the ceiling is both what
    # the original Cornell box does and what makes the lit variants work.
    ceiling = cast.get("ceiling_luminaire")
    if ceiling is not None:
        height = ceiling["extent_m"][1]
        placements.append({
            "record": ceiling, "role": "luminaire",
            "archetype": luminaire_archetype(ceiling),
            "position": (0.0, 0.0),
            "seat_height": room["height_m"] - height,
            "yaw": 0.0, "mounted": "ceiling",
        })
    return {"placements": placements, "room": room, "unplaced_props": unplaced}


def _reach(item: dict[str, Any]) -> tuple[float, float]:
    """Half-extents this placement occupies on the floor plane.

    A yawed footprint sweeps its own diagonal, so its axis-aligned reach comes
    from that rather than from the un-rotated side lengths.
    """
    width, depth = _footprint(item["record"])
    if item["yaw"]:
        radius = math.hypot(width, depth) / 2.0
        return radius, radius
    return width / 2.0, depth / 2.0


def _derive_room(placements: list[dict[str, Any]]) -> dict[str, float]:
    """Size the box around what it holds, and recentre the contents inside it.

    Measuring from the origin instead of from the content made the room pay
    twice for an off-centre layout: floor luminaires sit in their own row on
    one side, so a symmetric box grew to 4.8 m deep to hold 1.7 m of content.
    Centring first is what keeps the standoff even on all four walls.
    """
    low_x = min(item["position"][0] - _reach(item)[0] for item in placements)
    high_x = max(item["position"][0] + _reach(item)[0] for item in placements)
    low_z = min(item["position"][1] - _reach(item)[1] for item in placements)
    high_z = max(item["position"][1] + _reach(item)[1] for item in placements)
    offset_x = (low_x + high_x) / 2.0
    offset_z = (low_z + high_z) / 2.0
    for item in placements:
        item["position"] = (item["position"][0] - offset_x, item["position"][1] - offset_z)

    half_x = max(0.5, (high_x - low_x) / 2.0)
    half_z = max(0.5, (high_z - low_z) / 2.0)
    top = max(item["seat_height"] + item["record"]["extent_m"][1] for item in placements)
    # The near end of the working band, not the far end: guaranteeing a 1.2 m
    # standoff on every side adds 0.8 m to each dimension for a distance the
    # pose sampler already fits to whatever the room offers (it reduces the
    # radius down to MIN_FITTED_RADIUS_M rather than rejecting the pose).
    # Promising 0.8 m everywhere and more where the room allows is the honest
    # contract and keeps the box a box.
    margin = WORKING_RADIUS_M[0] + WALL_CLEARANCE_M
    return {
        "width_m": round(2.0 * (half_x + margin), 3),
        "depth_m": round(2.0 * (half_z + margin), 3),
        "height_m": round(max(MIN_CEILING_HEIGHT_M, top + 0.6), 3),
        "content_top_m": round(top, 3),
    }


# ---------------------------------------------------------------- stage GLB


def _pack_metallic_roughness(roughness_path: Path, metallic_path: Path | None,
                             target: Path) -> None:
    """glTF wants roughness in G and metallic in B of one image.

    TextureCan ships them as separate greyscale maps, so they are packed here.
    R is left at zero: this channel is glTF-unused, and writing occlusion into
    it would claim a map the registry does not provide.
    """
    rough = Image.open(roughness_path).convert("L")
    if metallic_path is not None:
        metal = Image.open(metallic_path).convert("L").resize(rough.size, Image.BILINEAR)
    else:
        metal = Image.new("L", rough.size, 0)
    zero = Image.new("L", rough.size, 0)
    target.parent.mkdir(parents=True, exist_ok=True)
    Image.merge("RGB", (zero, rough, metal)).save(target, format="PNG", optimize=True)


def _quad(origin: Sequence[float], edge_u: Sequence[float], edge_v: Sequence[float],
          repeat_u: float, repeat_v: float) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """One textured quad: positions, normals, UVs and indices.

    UVs carry the meter-repeat directly (0..width/physical_width), which is why
    no material-side scaling is needed: a 2 m TextureCan material tiles twice
    across a 4 m wall because the UV says so.
    """
    o = np.array(origin, dtype=np.float32)
    u = np.array(edge_u, dtype=np.float32)
    v = np.array(edge_v, dtype=np.float32)
    positions = np.stack([o, o + u, o + u + v, o + v]).astype(np.float32)
    normal = np.cross(u, v)
    normal = (normal / np.linalg.norm(normal)).astype(np.float32)
    normals = np.tile(normal, (4, 1)).astype(np.float32)
    uvs = np.array([[0.0, 0.0], [repeat_u, 0.0], [repeat_u, repeat_v], [0.0, repeat_v]],
                   dtype=np.float32)
    indices = np.array([0, 1, 2, 0, 2, 3], dtype=np.uint16)
    return positions, normals, uvs, indices


def wall_massing(room: dict[str, float], count: int, rng,
                 skip: Sequence[str] = ()) -> list[dict[str, Any]]:
    """Blocks standing against the walls, so the shell is not four flat planes.

    An outdoor box with a lid taken off is still a room until the walls stop
    being smooth. Massing them like neighbouring buildings gives the object
    something to sit among, and -- the point of it -- gives the indirect light
    somewhere to pick up a colour, because each block carries its own finish.
    Four walls of one material bounce one colour; eight blocks of eight
    materials bounce eight, which is the thing a real exterior does and a
    Cornell box does not.

    Sized against the room rather than in absolute metres so a 4 m box and a
    7 m box both read as buildings rather than as furniture.
    """
    width, depth, height = room["width_m"], room["depth_m"], room["height_m"]
    half_w, half_d = width / 2.0, depth / 2.0
    # A wall that has been taken out gets no blocks: they would stand in the
    # gap and shadow the room from the one direction the gap exists to admit.
    walls = tuple(w for w in ("north", "south", "east", "west")
                  if f"wall_{w}" not in set(skip))
    if not walls:
        return []
    out = []
    for index in range(count):
        wall = walls[index % len(walls)]
        # Wide enough to read as a mass, shallow enough to leave the room usable.
        w = rng.uniform(0.18, 0.42) * (width if wall in ("north", "south") else depth)
        d = rng.uniform(0.10, 0.28) * min(width, depth)
        h = rng.uniform(0.35, 0.95) * height
        if wall == "north":
            u = rng.uniform(-half_w, half_w - w)
            origin, size = (u, 0.0, -half_d), (w, h, d)
        elif wall == "south":
            u = rng.uniform(-half_w, half_w - w)
            origin, size = (u, 0.0, half_d - d), (w, h, d)
        elif wall == "east":
            v = rng.uniform(-half_d, half_d - w)
            origin, size = (half_w - d, 0.0, v), (d, h, w)
        else:
            v = rng.uniform(-half_d, half_d - w)
            origin, size = (-half_w, 0.0, v), (d, h, w)
        out.append({"role": f"massing_{index:02d}", "wall": wall,
                    "origin": origin, "size": size})
    return out


def _open_walls(count: int, rng) -> tuple[str, ...]:
    """Which walls to leave out, drawn per scene.

    Opposite walls are never both taken: a room open on two facing sides is a
    corridor with no back, and the hover path would frame the subject against
    sky from most of its arc. Two openings therefore meet at a corner.
    """
    if count <= 0:
        return ()
    walls = ["wall_north", "wall_south", "wall_east", "wall_west"]
    opposite = {"wall_north": "wall_south", "wall_south": "wall_north",
                "wall_east": "wall_west", "wall_west": "wall_east"}
    first = rng.choice(walls)
    if count == 1:
        return (first,)
    second = rng.choice([w for w in walls if w != first and w != opposite[first]])
    return tuple(sorted((first, second)))


def _box_faces(origin, size):
    """The five faces of a wall block that face into the room.

    The sixth is against the wall and is left out rather than drawn and hidden:
    a coincident pair of surfaces is z-fighting waiting to happen, and the
    normal AOV is ground truth here.
    """
    x, y, z = origin
    w, h, d = size
    return {
        "top":   ((x, y + h, z), (w, 0, 0), (0, 0, d), w, d),
        "front": ((x, y, z + d), (w, 0, 0), (0, h, 0), w, h),
        "back":  ((x + w, y, z), (-w, 0, 0), (0, h, 0), w, h),
        "left":  ((x, y, z), (0, 0, d), (0, h, 0), d, h),
        "right": ((x + w, y, z + d), (0, 0, -d), (0, h, 0), d, h),
    }


def build_stage_glb(room: dict[str, float], finishes: dict[str, dict[str, Any]],
                    registry_root: Path, out_glb: Path, work_dir: Path,
                    massing: list[dict[str, Any]] | None = None,
                    open_ceiling: bool = False,
                    open_walls: Sequence[str] = ()) -> dict[str, Any]:
    """Write the Cornell box as a GLB with embedded TextureCan PBR per face.

    Images must be embedded: `rewrite_glb` rejects a glTF whose image is not in
    a bufferView, because the downstream chain re-materialises every texture
    from the blob rather than trusting a path that may not survive the move.
    """
    width, depth, height = room["width_m"], room["depth_m"], room["height_m"]
    half_w, half_d = width / 2.0, depth / 2.0

    # Edge order is chosen so every cross(u, v) points *into* the room: the
    # normal AOV is ground truth here, so a face that shades from behind is a
    # defect rather than a cosmetic issue that double-siding papers over.
    faces = {
        "floor": ((-half_w, 0.0, -half_d), (0, 0, depth), (width, 0, 0), depth, width),
        "ceiling": ((-half_w, height, -half_d), (width, 0, 0), (0, 0, depth), width, depth),
        "wall_north": ((-half_w, 0.0, -half_d), (width, 0, 0), (0, height, 0), width, height),
        "wall_south": ((half_w, 0.0, half_d), (-width, 0, 0), (0, height, 0), width, height),
        "wall_east": ((half_w, 0.0, -half_d), (0, 0, depth), (0, height, 0), depth, height),
        "wall_west": ((-half_w, 0.0, half_d), (0, 0, -depth), (0, height, 0), depth, height),
    }

    blob = bytearray()
    buffer_views: list[dict[str, Any]] = []
    accessors: list[dict[str, Any]] = []
    images: list[dict[str, Any]] = []
    textures: list[dict[str, Any]] = []
    materials: list[dict[str, Any]] = []
    meshes: list[dict[str, Any]] = []
    nodes: list[dict[str, Any]] = []

    def add_view(payload: bytes, *, target: int | None = None) -> int:
        while len(blob) % 4:
            blob.append(0)
        offset = len(blob)
        blob.extend(payload)
        view = {"buffer": 0, "byteOffset": offset, "byteLength": len(payload)}
        if target is not None:
            view["target"] = target
        buffer_views.append(view)
        return len(buffer_views) - 1

    def add_accessor(array: np.ndarray, component: int, kind: str,
                     *, target: int, bounds: bool = False) -> int:
        view = add_view(array.tobytes(), target=target)
        accessor: dict[str, Any] = {"bufferView": view, "componentType": component,
                                    "count": int(array.shape[0]), "type": kind}
        if bounds:
            accessor["min"] = [float(v) for v in array.min(axis=0)]
            accessor["max"] = [float(v) for v in array.max(axis=0)]
        accessors.append(accessor)
        return len(accessors) - 1

    texture_cache: dict[str, int] = {}
    material_cache: dict[str, int] = {}

    def add_image(path: Path) -> int:
        """One glTF texture per distinct file.

        A box whose four walls share a finish would otherwise embed the same
        2K basecolour, normal and packed-MR four times over: deduplicating
        takes a six-face box from 115 MB to roughly the size of its distinct
        materials, and every copy is bytes the render chain re-extracts.
        """
        key = str(path.resolve())
        if key not in texture_cache:
            mime = "image/jpeg" if path.suffix.lower() in {".jpg", ".jpeg"} else "image/png"
            view = add_view(path.read_bytes())
            images.append({"bufferView": view, "mimeType": mime})
            textures.append({"source": len(images) - 1})
            texture_cache[key] = len(textures) - 1
        return texture_cache[key]

    def add_material(finish: dict[str, Any]) -> int:
        material_id = finish["id"]
        if material_id in material_cache:
            return material_cache[material_id]
        maps = finish["maps"]
        packed = work_dir / "stage_textures" / f"{material_id}_mr.png"
        if not packed.is_file():
            _pack_metallic_roughness(
                registry_root / maps["roughness"],
                registry_root / maps["metallic"] if "metallic" in maps else None,
                packed)
        materials.append({
            "name": f"abo_cornell_{material_id}",
            "pbrMetallicRoughness": {
                "baseColorTexture": {"index": add_image(registry_root / maps["base_color"])},
                "metallicRoughnessTexture": {"index": add_image(packed)},
                "metallicFactor": 1.0,
                "roughnessFactor": 1.0,
            },
            "normalTexture": {"index": add_image(registry_root / maps["normal_gl"])},
            "doubleSided": True,
        })
        material_cache[material_id] = len(materials) - 1
        return material_cache[material_id]

    finish_report: dict[str, Any] = {}
    if open_ceiling:
        # Taken out rather than made transparent or emissive: the renderer's
        # layer_count counts surfaces crossed, and a pane the sky shines
        # through would be counted as one.
        faces.pop("ceiling", None)
    for wall in open_walls:
        # A wall comes out for the same reason the lid does, and buys something
        # the lid cannot: the suns in the sky bank sit at 3.3-18.5 deg, far
        # below the cone an open ceiling leaves, so only a gap in a WALL lets
        # direct light reach the subject. What the camera sees through the gap
        # is world background, which carries no PBR ground truth -- the
        # renderer's `_mark_background_invalid` folds it into
        # GT_PBRInvalidMask off the depth pass, so those pixels are labelled
        # unsupervised rather than labelled zero.
        faces.pop(wall, None)

    for role, spec in faces.items():
        finish = finishes[role]
        physical = finish["physical_size_m"]
        origin, edge_u, edge_v, span_u, span_v = spec
        positions, normals, uvs, indices = _quad(
            origin, edge_u, edge_v, span_u / physical["width"], span_v / physical["height"])
        material_index = add_material(finish)

        meshes.append({"name": role, "primitives": [{
            "attributes": {
                "POSITION": add_accessor(positions, 5126, "VEC3", target=34962, bounds=True),
                "NORMAL": add_accessor(normals, 5126, "VEC3", target=34962),
                "TEXCOORD_0": add_accessor(uvs, 5126, "VEC2", target=34962),
            },
            "indices": add_accessor(indices.reshape(-1, 1), 5123, "SCALAR", target=34963),
            "material": material_index,
        }]})
        nodes.append({"name": role, "mesh": len(meshes) - 1})
        finish_report[role] = {"material_id": finish["id"], "category": finish.get("category"),
                               "repeat_u": round(span_u / physical["width"], 3),
                               "repeat_v": round(span_v / physical["height"], 3)}

    for block in massing or []:
        finish = finishes[block["role"]]
        physical = finish["physical_size_m"]
        material_index = add_material(finish)
        for face, (origin, edge_u, edge_v, span_u, span_v) in _box_faces(
                block["origin"], block["size"]).items():
            positions, normals, uvs, indices = _quad(
                origin, edge_u, edge_v, span_u / physical["width"],
                span_v / physical["height"])
            meshes.append({"name": f"{block['role']}_{face}", "primitives": [{
                "attributes": {
                    "POSITION": add_accessor(positions, 5126, "VEC3", target=34962, bounds=True),
                    "NORMAL": add_accessor(normals, 5126, "VEC3", target=34962),
                    "TEXCOORD_0": add_accessor(uvs, 5126, "VEC2", target=34962),
                },
                "indices": add_accessor(indices.reshape(-1, 1), 5123, "SCALAR", target=34963),
                "material": material_index,
            }]})
            nodes.append({"name": f"{block['role']}_{face}", "mesh": len(meshes) - 1})
        finish_report[block["role"]] = {
            "material_id": finish["id"], "category": finish.get("category"),
            "wall": block["wall"], "size_m": [round(v, 3) for v in block["size"]]}

    while len(blob) % 4:
        blob.append(0)
    gltf = {
        "asset": {"version": "2.0", "generator": COMPOSER_VERSION},
        "scene": 0,
        "scenes": [{"nodes": list(range(len(nodes)))}],
        "nodes": nodes,
        "meshes": meshes,
        "materials": materials,
        "textures": textures,
        "images": images,
        "accessors": accessors,
        "bufferViews": buffer_views,
        "buffers": [{"byteLength": len(blob)}],
    }
    json_chunk = json.dumps(gltf, separators=(",", ":")).encode("utf-8")
    json_chunk += b" " * (-len(json_chunk) % 4)
    out_glb.parent.mkdir(parents=True, exist_ok=True)
    with out_glb.open("wb") as handle:
        handle.write(struct.pack("<4sII", b"glTF", 2, 12 + 8 + len(json_chunk) + 8 + len(blob)))
        handle.write(struct.pack("<I4s", len(json_chunk), b"JSON"))
        handle.write(json_chunk)
        handle.write(struct.pack("<I4s", len(blob), b"BIN\x00"))
        handle.write(bytes(blob))
    return finish_report


def _texel_density(record: dict[str, Any], registry_root: Path) -> float:
    """Texels per metre this material resolves at its authored physical size."""
    try:
        with Image.open(registry_root / record["maps"]["base_color"]) as image:
            pixels = float(max(image.size))  # header only; pixels are not decoded
    except Exception:  # noqa: BLE001 - an unreadable header must not fail the draw
        pixels = float(ASSUMED_TEXTURE_PX)
    return pixels / float(record["physical_size_m"]["width"])


def choose_finishes(registry: dict[str, Any], seed: int, *, accent_walls: bool,
                    massing: list[dict[str, Any]] | None = None,
                    registry_root: Path, min_texel_px_per_m: float,
                    palette: dict[str, tuple[str, ...]] | None = None) -> dict[str, dict[str, Any]]:
    """Draw one TextureCan material per box face, at or above screen resolution.

    A surface whose texture carries fewer texels per metre than the sensor
    resolves is blurred by the optics alone, and its roughness/normal GT is
    then smoother than the surface it claims to describe.

    The threshold has to be evaluated at the distance the *wall* is seen from,
    not at the camera's closest approach to a prop.  Judging walls by the 0.8 m
    working radius demanded 1087 px/m and cut 41 of the 100 registry materials
    -- and cut them by category, taking every wood, fabric, brick and plaster
    and leaving concrete with two.  Walls in a 5 m box sit two to three metres
    away, where the sensor resolves nearer 350 px/m and the whole registry
    clears comfortably.  The caller passes the wall-distance figure.
    """
    materials = [record for record in registry["materials"]
                 if _texel_density(record, registry_root) >= min_texel_px_per_m]
    if not materials:
        raise ValueError(
            f"no registry material resolves {min_texel_px_per_m:.0f} px/m; "
            "the box cannot be finished at this standoff and field of view")
    by_category: dict[str, list[dict[str, Any]]] = {}
    for record in materials:
        by_category.setdefault(record.get("category", "other"), []).append(record)

    if palette is not None:
        # A named environment must not quietly become a different one. `draw`
        # falls back to the whole pool when a preference list matches nothing,
        # which is right for an untyped box and wrong here: a marble hall with
        # no marble left would render as a metal room under the name of a
        # marble hall, and the manifest would still say marble_hall.
        empty = sorted(role for role, families in palette.items()
                       if not any(by_category.get(family) for family in families))
        if empty:
            raise ValueError(
                f"environment palette has nothing for {empty} at {min_texel_px_per_m:.0f} px/m; "
                f"available categories: {sorted(by_category)}")

    def prefer_for(role: str, default: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(palette[role]) if palette and role in palette else default

    def draw(role: str, prefer: Iterable[str]) -> dict[str, Any]:
        """Draw from every preferred category at once, not the first that has
        anything in it.

        Taking the first non-empty category locked each role to whatever that
        one category held.  After the texel gate that was two concrete
        materials, so every wall and ceiling in the dataset would have come
        from a choice of two -- and walls are most of a Cornell box's frame
        area.  The preference list is an ordering of taste, not a fallback
        chain, so the pool is their union.
        """
        rng = _rng(seed, "finish", role)
        pool = [record for category in prefer for record in by_category.get(category, [])]
        return rng.choice(sorted(pool or materials, key=lambda r: r["id"]))

    finishes = {
        "floor": draw("floor", prefer_for("floor", ("wood", "tile", "concrete"))),
        "ceiling": draw("ceiling", prefer_for("ceiling", ("concrete", "plaster", "tile"))),
    }
    # Every block gets its own draw, keyed on its own role, and they are
    # required to differ from each other. Blocks that all landed on the same
    # material would be a more complicated wall rather than a row of
    # neighbouring buildings, and the whole reason for the massing is that the
    # indirect light picks up a different colour off each one.
    used: set[str] = set()
    for block in massing or []:
        for attempt in range(8):
            pick = draw(f"{block['role']}#{attempt}",
                        prefer_for("massing", ("concrete", "brick", "tile", "metal")))
            if pick["id"] not in used:
                break
        used.add(pick["id"])
        finishes[block["role"]] = pick
    wall_default = draw("wall", prefer_for("wall", ("concrete", "brick", "tile")))
    for role in ("wall_north", "wall_south", "wall_east", "wall_west"):
        finishes[role] = wall_default
    if accent_walls:
        # The classic Cornell pair: two facing walls differ so colour bleeding
        # is visible in the interreflection the box exists to produce.
        #
        # v3 draws both accents from one pool and then requires them to differ,
        # rather than giving each its own narrow preference list. Under v2 the
        # west accent's list was marble + rock + fabric, which is 11 materials
        # in this registry -- across 100 scenes it produced 11 distinct walls
        # against 50 for the main wall, with one material appearing 13 times.
        # Distinctness is what the accent is for, so it is enforced rather than
        # left to two lists happening not to overlap.
        pool = prefer_for("accent", ACCENT_CATEGORIES)
        east = draw("accent_east", pool)
        west = draw("accent_west", pool)
        if west["id"] == east["id"] or west["id"] == wall_default["id"]:
            rng = _rng(seed, "accent_west_retry")
            options = [record for category in pool for record in by_category.get(category, [])
                       if record["id"] not in {east["id"], wall_default["id"]}]
            if options:
                west = rng.choice(sorted(options, key=lambda r: r["id"]))
        finishes["wall_east"] = east
        finishes["wall_west"] = west
    return finishes


# ---------------------------------------------------------------- NIR priors


def load_nir_classes(path: Path) -> dict[str, dict[str, Any]]:
    """The class table plus its fallbacks, in one namespace."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema") != "class_band_reflectance_v1":
        raise ValueError(f"unexpected NIR class schema in {path}")
    return {**payload["classes"], **payload["fallback"]}


def _image_luma_pivot(path: Path) -> float | None:
    """Pivot luminance of a base-colour map, in linear light.

    The transfer term is `L(x) / pivot - 1`, so the pivot decides which texel
    maps to the class mean.  `class_band_reflectance_v1` writes that pivot as
    median(L); this uses the *mean* instead, and the reason is physical:
    `rho_854.mean` is the class's mean reflectance, reflectance is an energy
    ratio, and energy averages linearly -- so the texture's mean is what should
    land on it.

    It also matters in practice.  ABO base-colour maps are often a dark ground
    with a bright motif, which drags the median far below the mean: one lamp
    map measured median 0.0024 against mean 0.1406, so `L/median` reached 325
    and 19% of its texels clipped against the [0, 0.95] reflectance bound.
    Clipping destroys exactly the contrast the transfer term exists to carry --
    a wood asset retained 35% of its visible contrast where alpha asks for 55%.
    On the mean the same asset retains 54%, and clipping falls to 15%.

    sRGB is undone first: a pivot taken on encoded bytes sits about a stop off.
    """
    try:
        with Image.open(path) as image:
            small = image.convert("RGB").resize((256, 256), Image.BILINEAR)
    except Exception:  # noqa: BLE001 - an unreadable map falls back to a flat prior
        return None
    a = np.asarray(small, dtype=np.float32) / 255.0
    linear = np.where(a <= 0.04045, a / 12.92, ((a + 0.055) / 1.055) ** 2.4)
    luma = 0.299 * linear[..., 0] + 0.587 * linear[..., 1] + 0.114 * linear[..., 2]
    value = float(luma.mean())
    return value if value > 1e-4 else None


def _slot_images(gltf: dict[str, Any], material: dict[str, Any]) -> dict[str, int]:
    """Resolve a material's texture slots to glTF image indices."""
    textures = gltf.get("textures") or []
    pbr = material.get("pbrMetallicRoughness") or {}
    slots = {"base_color": pbr.get("baseColorTexture"),
             "metallic_roughness": pbr.get("metallicRoughnessTexture")}
    out: dict[str, int] = {}
    for name, info in slots.items():
        if not info:
            continue
        index = int(info.get("index", -1))
        if 0 <= index < len(textures):
            source = textures[index].get("source")
            if isinstance(source, int):
                out[name] = source
    return out


def _metal_fraction(material: dict[str, Any], mr_path: Path | None) -> float:
    """How metallic this material is, from its map where it has one.

    glTF puts metallic in the blue channel of the metallic-roughness image and
    multiplies it by `metallicFactor`, so both are read; a material with only
    the factor still classifies correctly.
    """
    pbr = material.get("pbrMetallicRoughness") or {}
    factor = float(pbr.get("metallicFactor", 1.0))
    if mr_path is None or not mr_path.is_file():
        return factor
    try:
        with Image.open(mr_path) as image:
            small = image.convert("RGB").resize((128, 128), Image.BILINEAR)
    except Exception:  # noqa: BLE001
        return factor
    blue = np.asarray(small, dtype=np.float32)[..., 2] / 255.0
    return float(blue.mean()) * factor


def assign_nir_prior(classes: dict[str, dict[str, Any]], *, product_type: str | None = None,
                     texturecan_category: str | None = None, metal_fraction: float = 0.0,
                     pivot_luma: float | None = None) -> dict[str, Any]:
    """Pick a class for one material and resolve it into shader constants.

    Metal is decided from the asset rather than the catalogue: a chair with a
    chromed frame is a conductor whatever `product_type` says, and its NIR
    behaviour belongs in Fresnel rather than in a diffuse map.  Everything else
    goes through the product type, then the broad dielectric fallback -- which
    is a documented prior with a stated spread, not a grey derived from RGB.
    """
    if metal_fraction >= METAL_CLASS_THRESHOLD:
        name = "bare_metal"
    elif texturecan_category and texturecan_category in NIR_CLASS_BY_TEXTURECAN_CATEGORY:
        name = NIR_CLASS_BY_TEXTURECAN_CATEGORY[texturecan_category]
    elif product_type and product_type in NIR_CLASS_BY_PRODUCT_TYPE:
        name = NIR_CLASS_BY_PRODUCT_TYPE[product_type]
    else:
        name = "unknown_dielectric"
    record = classes[name]
    albedo_channel = bool(record["albedo_channel"])
    # Without a usable normaliser the transfer term has no pivot, so the class
    # mean is used flat rather than being multiplied by an invented ratio.
    alpha = float(record["rgb_structure_weight"]) if (albedo_channel and pivot_luma) else 0.0
    return {
        "class": name,
        "rho_854": float(record["rho_854"]["mean"]),
        "alpha": alpha,
        "albedo_channel": albedo_channel,
        "pivot_luma": float(pivot_luma) if pivot_luma else None,
        "pivot": "mean_linear_luma",
        "confidence": record.get("confidence"),
        "tier": record.get("tier"),
        "metal_fraction": round(float(metal_fraction), 4),
        "matched_on": ("metallic" if metal_fraction >= METAL_CLASS_THRESHOLD
                       else "texturecan_category" if texturecan_category in NIR_CLASS_BY_TEXTURECAN_CATEGORY
                       else "product_type" if product_type in NIR_CLASS_BY_PRODUCT_TYPE
                       else "fallback"),
    }


# ---------------------------------------------------------------- manifest


def _blender_matrix(position: tuple[float, float], seat_height: float, yaw: float,
                    record: dict[str, Any]) -> list[list[float]]:
    """Instance transform in Blender world space (Z-up).

    The importer maps glTF +Y to Blender +Z, so an asset's own y_min becomes
    its z_min: seating it on a surface means lifting by (seat - y_min) rather
    than by seat alone.  17% of ABO assets are not authored with y_min = 0, so
    assuming a floor origin drops them through the floor or floats them.
    """
    cos_a, sin_a = math.cos(yaw), math.sin(yaw)
    lift = seat_height - float(record["bounds_lo"][1])
    return [
        [cos_a, -sin_a, 0.0, float(position[0])],
        [sin_a, cos_a, 0.0, float(position[1])],
        [0.0, 0.0, 1.0, float(lift)],
        [0.0, 0.0, 0.0, 1.0],
    ]


def write_semantics_csv(path: Path, placements: Sequence[dict[str, Any]]) -> int:
    """The luminaire catalogue `lighting.lighting_assets` reads.

    It keys on `super_category == "lighting"` and returns `main_category`,
    which `placement_for` turns into the emitter height inside the bbox.  It
    raises when the file names no lighting asset at all, so a scene composed
    without a luminaire must not be handed to the fixture stage.

    The `id` column is the *source* asset id, not the instance id: the Blender
    side looks each mesh up by its `hssd_source_id` custom property, so keying
    this file by instance would match nothing and silently leave the room dark.
    One asset used twice therefore contributes one row, and both of its
    instances get a fixture light.
    """
    rows: dict[str, dict[str, Any]] = {}
    for item in placements:
        if item["role"] != "luminaire":
            continue
        rows.setdefault(item["record"]["id"], {
            "id": item["record"]["id"],
            "super_category": LIGHTING_SUPER_CATEGORY,
            "main_category": item["archetype"],
            "name": (item["record"].get("name") or "")[:80],
        })
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["id", "super_category", "main_category", "name"])
        writer.writeheader()
        for row in rows.values():
            writer.writerow(row)
    return len(rows)


def _alpha_evidence(bundle: Path, material_index: int) -> dict[str, Any]:
    """What the material's alpha actually is, not just what it declares.

    `alphaMode: BLEND` says alpha should be honoured; it does not say any of it
    is below 1. Measured across this corpus, 58 materials declare BLEND or MASK
    and 21 of them are effectively opaque, so acting on the declaration alone
    would discard a third of them for nothing.

    The prepare stage decides `pbr_training_valid = training_valid and not
    glass`, and its glass test is a name containing "glass" or a
    KHR_materials_transmission factor. ABO uses neither -- zero materials here
    carry the extension -- so 154 transmissive surfaces were rendering with a
    metallic-roughness target that cannot describe them. These two fields are
    what lets that test see them, and they are optional: a consumer written
    before this must treat their absence as "not measured", not as "opaque".
    """
    if not bundle.is_file():
        return {}
    try:
        document = json.loads(bundle.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    materials = document.get("materials") or []
    if material_index >= len(materials):
        return {}
    pbr = (materials[material_index].get("pbrMetallicRoughness") or {})
    factor = float((pbr.get("baseColorFactor") or [1.0, 1.0, 1.0, 1.0])[3])
    evidence: dict[str, Any] = {"base_color_factor_alpha": factor}

    index = (pbr.get("baseColorTexture") or {}).get("index")
    textures = document.get("textures") or []
    images = document.get("images") or []
    if index is None or index >= len(textures):
        return evidence
    source = textures[index].get("source")
    if source is None or source >= len(images):
        return evidence
    uri = images[source].get("uri")
    if not uri:
        return evidence
    path = bundle.parent / uri
    if not path.is_file():
        return evidence
    try:
        image = Image.open(path)
        if image.mode not in ("RGBA", "LA", "PA"):
            # No alpha channel at all is evidence of opacity, and different
            # from having one we could not read.
            evidence["base_color_texture_alpha_fraction"] = 0.0
            return evidence
        alpha = np.asarray(image.convert("RGBA"))[..., 3].astype(np.float32) / 255.0
    except OSError:
        return evidence
    evidence["base_color_texture_alpha_fraction"] = float((alpha < 0.95).mean())
    return evidence




def build_manifest(scene_id: str, layout: dict[str, Any], stage_glb: Path,
                   out_dir: Path, *, basisu: Path, nir_classes: dict[str, Any] | None,
                   stage_finishes: dict[str, dict[str, Any]],
                   asset_cache: Path | None = None) -> dict[str, Any]:
    """Convert every asset once and assemble the HSSD-shaped scene manifest.

    `nir_classes` of None leaves `nir_priors` empty, which is how the prepare
    stage is told to keep its visible-luminance NIR derivation.
    """
    cache: dict[str, dict[str, Any]] = {}

    def bundle(key: str, source: Path, *, shared: bool = True) -> dict[str, Any]:
        """Convert one asset, reusing a shared bundle when the source matches.

        The cache used to be keyed by scene, so an ABO asset appearing in ten
        scenes was decoded and re-encoded ten times into ten directories holding
        byte-identical output. Measured over 150 scenes: 2,141 bundle instances
        for 693 distinct assets, about 39 GB of duplicate bytes, and the
        duplicate work to produce them.

        `shared=False` is for the stage, which is generated per scene and is
        genuinely different every time -- content-addressing it would spend a
        hash to prove that. It stays beside the scene it belongs to.
        """
        if key in cache:
            return cache[key]
        if not shared or asset_cache is None:
            print(f"[abo-cornell] convert asset={key}", flush=True)
            cache[key] = rewrite_glb(source=source, out=out_dir / "assets" / key, basisu=basisu)
            return cache[key]

        # Keyed on the source's content, not its id: an id is a promise that the
        # bytes behind it never change, and this week has been a run of names
        # promising identities they did not have.
        digest = sha256(source)
        published = asset_cache / f"{key}-{digest[:16]}"
        record_path = published / "bundle.json"
        if record_path.is_file():
            cache[key] = json.loads(record_path.read_text(encoding="utf-8"))
            return cache[key]

        print(f"[abo-cornell] convert asset={key} -> shared cache", flush=True)
        # The leaf directory name is not cosmetic: `rewrite_glb` derives each
        # material's join key from it (`material_marker(out.name, index)`), and
        # that key is written into the glTF at conversion time. Building into a
        # directory called `<id>-<sha>.<pid>` therefore stamped the pid into
        # every material name, and `prepare` refused every scene that touched a
        # freshly converted asset because those names could not be joined to the
        # manifest audit. Fifty scenes, all of them.
        #
        # So the pid disambiguates a level up and the leaf keeps the asset id.
        # The final directory is still named for the content hash -- renaming
        # afterwards is safe precisely because the names are already inside the
        # file by then.
        staging = asset_cache / ".staging" / str(os.getpid()) / key
        if staging.exists():
            shutil.rmtree(staging)
        record = rewrite_glb(source=source, out=staging, basisu=basisu)
        # Paths inside the record must name where the bundle ends up, not where
        # it was built, since the manifest hands them to Blender verbatim.
        record = json.loads(json.dumps(record).replace(str(staging), str(published)))
        record_staged = staging / "bundle.json"
        record_staged.write_text(json.dumps(record, indent=1), encoding="utf-8")
        published.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.rename(staging, published)
        except OSError:
            # Another compose published the same content first. bundle.json is
            # written before the rename, so anything that arrived here is whole;
            # theirs is as good as ours and ours is the one that gets discarded.
            shutil.rmtree(staging, ignore_errors=True)
            if not record_path.is_file():
                raise
            record = json.loads(record_path.read_text(encoding="utf-8"))
        # The pid directory exists only to keep two composes apart; once its
        # bundle has been renamed out it is an empty directory that nothing will
        # ever revisit, because the next run has a different pid.
        try:
            staging.parent.rmdir()
        except OSError:
            pass                      # another convert of ours is still using it
        cache[key] = record
        return record

    stage_bundle = bundle("stage", stage_glb, shared=False)

    product_type_by_asset = {item["record"]["id"]: item["record"]["product_type"]
                             for item in layout["placements"]}
    instances: list[dict[str, Any]] = []
    for index, item in enumerate(layout["placements"]):
        record = item["record"]
        source = Path(record["path"])
        asset = bundle(record["id"], source)
        instance_id = f"object_{index:04d}"
        item["instance_id"] = instance_id
        instances.append({
            "instance_id": instance_id,
            "source_id": record["id"],
            # Read downstream only to split openings from content by path; ABO
            # has no openings, so this must not look like one.
            "source_config": f"abo/objects/{record['product_type'].lower()}/{record['id']}.json",
            "source_glb": str(source),
            "source_sha256": asset["source_sha256"],
            "bundle": asset["gltf"],
            "blender_matrix": _blender_matrix(item["position"], item["seat_height"],
                                              item["yaw"], record),
            "motion_type": "STATIC",
            "abo_role": item["role"],
            "abo_product_type": record["product_type"],
            "abo_archetype": item.get("archetype"),
            "abo_host_id": item.get("host_id"),
        })

    # One NIR class per material slot, keyed by the marker Blender resolves the
    # material by, so the prepare stage can look it up without knowing ABO.
    # Left empty unless the class prior was asked for: an empty table is the
    # signal that keeps `_pseudo_nir` in place downstream.
    nir_priors: dict[str, dict[str, Any]] = {}
    if nir_classes is not None:
        # `build_stage_glb` emits one material per distinct finish, in the order it
        # walks the faces, so the same walk reproduces the material index here.
        stage_material_order: list[dict[str, Any]] = []
        for role in BOX_ROLES:
            finish = stage_finishes[role]
            if finish["id"] not in {seen["id"] for seen in stage_material_order}:
                stage_material_order.append(finish)
        for asset_id, record in cache.items():
            gltf = read_gltf_json(Path(record["source"]))
            images = {int(i): entry["output"] for i, entry in enumerate(record.get("images", []))}
            product_type = None if asset_id == "stage" else product_type_by_asset.get(asset_id)
            for source_material in record.get("source_materials", []):
                index = int(source_material["material_index"])
                material = source_material["material"]
                slots = _slot_images(gltf, material)
                asset_dir = Path(record["gltf"]).parent
                base_path = (asset_dir / images[slots["base_color"]]) if "base_color" in slots else None
                mr_path = (asset_dir / images[slots["metallic_roughness"]]) if "metallic_roughness" in slots else None
                category = None
                if asset_id == "stage":
                    # Stage materials are emitted one per distinct finish, in the
                    # order `build_stage_glb` created them.
                    finish = stage_material_order[index] if index < len(stage_material_order) else None
                    category = (finish or {}).get("category")
                prior = assign_nir_prior(
                    nir_classes, product_type=product_type, texturecan_category=category,
                    metal_fraction=_metal_fraction(material, mr_path),
                    pivot_luma=_image_luma_pivot(base_path) if base_path else None)
                prior["asset_id"] = asset_id
                prior["material_index"] = index
                nir_priors[material_marker(asset_id, index)] = prior

    material_audit: list[dict[str, Any]] = []
    for asset_id, record in cache.items():
        classified = []
        for source_material in record.get("source_materials", []):
            audit = classify_material(scene_id=scene_id, asset_id=asset_id,
                                      material_index=int(source_material["material_index"]),
                                      material=source_material["material"],
                                      source_sha256=record["source_sha256"],
                                      asset_metadata={})
            audit.setdefault("source_mr", {}).update(
                _alpha_evidence(Path(record["gltf"]),
                                int(source_material["material_index"])))
            classified.append(audit)
            material_audit.append(audit)
        record["material_audit"] = classified
        record["asset_metadata"] = {}

    return {
        "schema": HSSD_SCENE_SCHEMA,
        "composer_schema": SCHEMA,
        "composer_version": COMPOSER_VERSION,
        "scene_id": scene_id,
        "source_scene": "abo_cornell_box",
        "stage": {"source_config": "abo/stage/cornell_box.json", "source_glb": str(stage_glb),
                  "bundle": stage_bundle["gltf"], "source_sha256": sha256(stage_glb)},
        "instances": instances,
        "unresolved_instances": [],
        "asset_cache": cache,
        "material_audit": material_audit,
        "remediation_summary": _summary(material_audit),
        "basisu": str(basisu),
        "texture_policy": "ktx2_png_required_no_factor_fallback",
        "room": layout["room"],
        # A closed shell cannot use the day curriculum: its sun, sky and window
        # layers contribute nothing and its baseline variant switches every
        # fixture off, so the box carries its own profile through to the
        # renderer, sized against the floor area recorded above.
        "lighting_profile": BOX_LIGHTING_PROFILE,
        "nir_prior_schema": NIR_PRIOR_SCHEMA,
        "nir_model": "class_band_prior_v1" if nir_priors else "derived_pseudo_nir",
        "nir_priors": nir_priors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--index", type=Path, required=True,
                        help="abo_object_index.json from build_abo_object_index.py --support")
    parser.add_argument("--registry", type=Path,
                        default=Path("/bean/ir_pbr_assets/texturecan_structural_extended_v2/registry.lock.json"))
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--scene-id", default=None, help="default: abo_cornell_<seed>")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--hosts", type=int, default=1,
                        help="support hosts; the multi-object character comes from props on them")
    parser.add_argument("--props", type=int, default=6)
    parser.add_argument("--luminaires", type=int, default=1)
    parser.add_argument("--hfov-deg", type=float, default=DEFAULT_HFOV_DEG,
                        help="camera horizontal FOV; default is the JAI FS-1600 with a 6 mm lens")
    parser.add_argument("--frame-width-px", type=int, default=DEFAULT_FRAME_WIDTH_PX)
    parser.add_argument("--wall-massing", type=int, default=0,
                        help="blocks standing against the walls, each with its own finish, "
                             "so the shell reads as neighbouring buildings rather than four "
                             "flat planes and the indirect light picks up a different colour "
                             "off each")
    parser.add_argument("--environment-type", choices=sorted(ENVIRONMENT_TYPES), default=None,
                        help="pin the material families and the shell openings to one real "
                             "space; --open-ceiling/--open-walls still override it")
    parser.add_argument("--open-walls", type=int, default=0, choices=(0, 1, 2),
                        help="omit this many walls, so low sun and a view out reach the room")
    parser.add_argument("--open-ceiling", action="store_true",
                        help="leave the lid off for an exterior. The hover arc starts level "
                             "with the object and climbs, so the camera never looks up into "
                             "the gap; what it buys is sky as the only light from above")
    parser.add_argument("--accent-walls", action="store_true",
                        help="give two facing walls contrasting finishes (classic Cornell bleed)")
    parser.add_argument("--nir-class-prior", action=argparse.BooleanOptionalAction, default=False,
                        help="assign NIR reflectance from the physical material class table. "
                             "Off by default: the pipeline's own derived_pseudo_nir is the "
                             "agreed model for this dataset. The prior is better grounded but "
                             "attenuates within-texture detail to its class alpha (ceramic 0.15 "
                             "keeps 15%% of the visible relative contrast), so it is opt-in.")
    parser.add_argument("--nir-classes", type=Path, default=DEFAULT_NIR_CLASSES,
                        help="class_band_reflectance_v1.json consulted by --nir-class-prior")
    parser.add_argument("--basisu", type=Path, default=Path("basisu"),
                        help="only used for KTX2 sources; ABO ships PNG/JPEG and never invokes it")
    parser.add_argument("--asset-cache", type=Path, default=None,
                        help="directory holding converted asset bundles keyed by source content, "
                             "shared across scenes. Defaults to `_asset_cache` beside the scene "
                             "directory; pass an explicit path to relocate it, or --no-asset-cache "
                             "to keep every bundle inside its own scene as before.")
    parser.add_argument("--no-asset-cache", dest="asset_cache", action="store_const", const=None,
                        help="disable the shared cache (the pre-2026-09-09 behaviour)")
    args = parser.parse_args()
    if args.asset_cache is None and "--no-asset-cache" not in sys.argv:
        args.asset_cache = args.out.parent / "_asset_cache"

    index = json.loads(args.index.read_text(encoding="utf-8"))
    if not index.get("support_pass"):
        parser.error("index was built without --support; support bands are required to place props")
    objects = index["objects"]

    registry = json.loads(args.registry.read_text(encoding="utf-8"))
    registry_root = args.registry.parent

    scene_id = args.scene_id or f"abo_cornell_{args.seed:04d}"
    out_dir = args.out
    out_dir.mkdir(parents=True, exist_ok=True)

    limits = camera_limits(args.hfov_deg, args.frame_width_px)
    print(f"[abo-cornell] optics hfov={limits['hfov_deg']:.2f} deg "
          f"frame={limits['frame_width_near_m']:.3f}-{limits['frame_width_far_m']:.3f} m "
          f"prop_cap={limits['max_prop_extent_m']:.3f} m "
          f"texel_floor={limits['min_texel_px_per_m']:.0f} px/m", flush=True)
    cast = select_cast(objects, hosts=args.hosts, props=args.props,
                       luminaires=args.luminaires, seed=args.seed,
                       max_prop_extent_m=limits["max_prop_extent_m"])
    layout = compose(cast, seed=args.seed)
    room = layout["room"]
    dropped = layout["unplaced_props"]
    print(f"[abo-cornell] room {room['width_m']}x{room['depth_m']}x{room['height_m']} m "
          f"placements={len(layout['placements'])} unplaced_props={len(dropped)}", flush=True)

    # Walls are judged at the distance they are actually seen from -- roughly
    # half the room across, since the camera works around objects near its
    # centre -- rather than at the camera's closest approach to a prop.
    wall_distance = max(min(room["width_m"], room["depth_m"]) / 2.0, WORKING_RADIUS_M[1])
    wall_texel_floor = args.frame_width_px / frame_width_m(wall_distance, args.hfov_deg)
    print(f"[abo-cornell] wall texel floor {wall_texel_floor:.0f} px/m at {wall_distance:.2f} m "
          f"(prop-distance floor would be {limits['min_texel_px_per_m']:.0f})", flush=True)
    # Which walls come out is drawn per scene, and drawn before the massing so
    # the blocks can avoid them.
    # A type supplies the openings unless the caller named them itself, so
    # --environment-type outdoor_street is one flag rather than three that have
    # to agree with each other.
    preset = ENVIRONMENT_TYPES.get(args.environment_type) if args.environment_type else None
    if preset is not None:
        if not args.open_ceiling:
            args.open_ceiling = bool(preset["open_ceiling"])
        if not args.open_walls:
            args.open_walls = int(preset["open_walls"])
        print(f"[abo-cornell] environment {args.environment_type} "
              f"(open_ceiling={args.open_ceiling} open_walls={args.open_walls})", flush=True)
    open_walls = _open_walls(args.open_walls, _rng(args.seed, "open_walls"))
    if open_walls:
        print(f"[abo-cornell] open walls {', '.join(open_walls)}", flush=True)
    blocks = wall_massing(room, args.wall_massing, _rng(args.seed, "massing"),
                          skip=open_walls) if args.wall_massing else []
    finishes = choose_finishes(registry, args.seed, accent_walls=args.accent_walls,
                               massing=blocks,
                               registry_root=registry_root,
                               min_texel_px_per_m=wall_texel_floor,
                               palette=preset["palette"] if preset else None)
    stage_glb = out_dir / "stage" / "cornell_box.glb"
    finish_report = build_stage_glb(room, finishes, registry_root, stage_glb, out_dir,
                                    massing=blocks, open_ceiling=args.open_ceiling,
                                    open_walls=open_walls)
    if blocks:
        print(f"[abo-cornell] massing {len(blocks)} blocks, "
              f"{len({finishes[b['role']]['id'] for b in blocks})} distinct finishes"
              + (" · open ceiling" if args.open_ceiling else ""), flush=True)
    # Name a wall that was actually built: wall_north may have been taken out.
    a_wall = next((role for role in BOX_ROLES
                   if role.startswith("wall_") and role in finish_report), None)
    print(f"[abo-cornell] stage {stage_glb.name} "
          f"floor={finish_report['floor']['material_id']} "
          f"{a_wall}={finish_report[a_wall]['material_id'] if a_wall else 'none'}",
          flush=True)

    nir_classes = load_nir_classes(args.nir_classes) if args.nir_class_prior else None
    manifest = build_manifest(scene_id, layout, stage_glb, out_dir, basisu=args.basisu,
                              asset_cache=args.asset_cache,
                              nir_classes=nir_classes, stage_finishes=finishes)
    manifest["structural_finish"] = finish_report
    # Which pool the shell was drawn from, so a resume can tell an environment
    # scene from an interior one without opening the finishes.
    manifest["structural_registry"] = str(args.registry)
    if args.environment_type:
        manifest["environment_type"] = args.environment_type
    manifest["camera_limits"] = limits
    if blocks:
        manifest["wall_massing"] = blocks
    if args.open_ceiling or open_walls:
        # An opening of any kind means the sky, not the fixtures, is what lights
        # the room -- so the closed-box curriculum is the wrong variant table
        # and the sky bank is needed. A wall counts for this exactly as the
        # ceiling does.
        missing = [name for name in OPEN_ENVIRONMENTS if not (HDRI_DIR / f"{name}.hdr").is_file()]
        if missing:
            raise SystemExit(f"--open-ceiling needs the sky bank; missing {missing} under {HDRI_DIR}")
        manifest["open_ceiling"] = bool(args.open_ceiling)
        if open_walls:
            manifest["open_walls"] = list(open_walls)
            # Which way the gap faces decides where the sun has to be put, so
            # it travels with the scene rather than being re-derived downstream.
            manifest["open_wall_azimuth_deg"] = WALL_AZIMUTH_DEG[open_walls[0]]
        manifest["lighting_profile"] = OPEN_LIGHTING_PROFILE
        manifest["environment_hdri_dir"] = str(HDRI_DIR)
    digest_inputs: dict[str, Any] = {
        "version": COMPOSER_VERSION, "seed": args.seed, "room": room,
        "instances": [(i["source_id"], i["blender_matrix"]) for i in manifest["instances"]],
        "finishes": finish_report,
    }
    # The structural keys join the digest only when they are used. A scene with
    # a closed, unmassed box hashes to what it hashed to before they existed,
    # so the 200 scenes already composed stay comparable with the ones composed
    # after this.
    if blocks:
        digest_inputs["massing"] = blocks
    if args.open_ceiling:
        digest_inputs["open_ceiling"] = True
    if open_walls:
        digest_inputs["open_walls"] = list(open_walls)
    if args.environment_type:
        digest_inputs["environment_type"] = args.environment_type
    manifest["composition_digest"] = stable_digest(digest_inputs)

    lamp_count = write_semantics_csv(out_dir / "abo_semantics.csv", layout["placements"])
    (out_dir / "scene_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    selection = [{
        "instance_id": item["instance_id"], "id": item["record"]["id"], "role": item["role"],
        "product_type": item["record"]["product_type"], "extent_m": item["record"]["extent_m"],
        "seat_height_m": round(item["seat_height"], 4), "host_id": item.get("host_id"),
        "archetype": item.get("archetype"), "name": item["record"].get("name", ""),
    } for item in layout["placements"]]
    (out_dir / "object_selection.json").write_text(
        json.dumps({"schema": SCHEMA, "scene_id": scene_id, "seed": args.seed,
                    "room": room, "objects": selection,
                    "unplaced_props": layout["unplaced_props"]}, indent=2), encoding="utf-8")

    print(f"[abo-cornell] nir model={manifest['nir_model']} "
          f"priors={len(manifest['nir_priors'])}", flush=True)
    print(f"[abo-cornell] scene={scene_id} instances={len(manifest['instances'])} "
          f"luminaires={lamp_count} digest={manifest['composition_digest'][:12]}", flush=True)
    print(f"[abo-cornell] next: blender_build_scene.py --manifest {out_dir / 'scene_manifest.json'} "
          f"--out-blend {out_dir / 'source.blend'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
