#!/usr/bin/env python3
"""Korean-apartment Infinigen scene generator (env-managed wrapper).

Infinigen must run *from its install folder* even when pip-installed, so this
wrapper invokes ``python -m infinigen_examples.generate_indoors`` with cwd set to
the install dir and the install's python. Configure via env:

    INFINIGEN_DIR     install folder (default: ~/module/infinigen)
    INFINIGEN_PYTHON  python with the infinigen+bpy env
                      (default: ~/miniconda3/envs/infinigen/bin/python)

Why a wrapper and not bare ``--seed``:  a "Korean urban apartment" is a FLOOR-PLAN
prior, not a seed. The seed only fixes randomness within a config. So we encode an
8-digit seed ``AABBCCDD`` (unit type / layout variant / furnishing density / camera)
and translate it into a predefined floor plan + verified gin overrides. The big
living-room window ("통창") is forced via the floor plan's window ``is_panoramic``
flag (Infinigen's panoramic windows are ~floor-to-ceiling, full-wall openings),
which is far more reliable than waiting for the random WindowFactory to roll one.

VERIFIED against Infinigen 1.19.1 (~/module/infinigen):
  - generate_indoors args: -s/--seed, --task, --output_folder, -g/--configs
    (no .gin needed but accepted), -p/--overrides (gin params).
  - Solver is @gin.configurable -> ``Solver.floor_plan='<path>'`` works.
  - floor_plan dispatch: a ``.json`` path is json.load'd and each entry's
    ``shape`` string is eval'd (so we emit shapes as ``"shapely.box(...)"``).
  - compose_indoors is @gin.configurable and reads num_floating /
    enable_collision_floating / enable_collision_solved from **overrides.
  - Floor-plan schema keys: rooms / doors / opens / interiors / windows, each a
    dict of name -> {"shape": <shapely expr>, [is_panoramic: 1]}.

NOT yet wired (need code edits in infinigen, not gin): killing the random
curtain/shutter (WindowFactory is not @gin.configurable), per-seed material bias
(the wall palette below is a fixed global default, not something this wrapper can
vary via -p/--override), camera profile placement. The seed's camera digits are
recorded in metadata only.

2026-08-11: patched the INFINIGEN_DIR install directly (not gin-configurable, so
no override path exists) to address flat wall textures and low structural
diversity in generated apartments:
  - assets/composition/material_assignments.py: `wall` (per-wall-face default,
    used by living-room/bedroom/hallway/dining-room/etc) now mixes in Brick and
    Wood alongside Plaster/Tile instead of just Plaster+Tile; new `wall_accent`
    list (richer Plaster/Brick/Tile/Wood mix) feeds the existing feature-wall
    mechanism in core/.../room/decorate.py's `room_wall_alternative_fns`
    (previously that accent slot only ever resampled plain Plaster).
  - floorplan_gen.py's `build_apartment`: corridor/LDK/bedroom-band topology
    now varies per seed (corridor along the short vs long axis, LDK band on
    either side of the corridor) via exact rotation/reflection of the existing
    validated tiling, instead of always the same "corridor mid-height, LDK
    south" layout. Room-count range widened 6-9 -> 5-10.
These are machine-local edits to ~/module/infinigen (outside this repo's git,
same as the Mitsuba build dirs) -- re-apply on any fresh Infinigen checkout.

This script does not run Infinigen itself unless asked; default is --dry-run-safe:
it always prints the exact command. Use --run to actually launch (heavy: needs the
conda env + Blender + GPU).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from floorplan_gen import (  # noqa: E402  (sibling module)
    MODERN_OFFICE_ARCHETYPE,
    MODERN_OFFICE_PROFILE,
    SINGLE_ROOM_TYPES,
    build_floor_plan,
    build_single_room_plan,
    modern_office_metadata,
    modern_office_partition_spec,
    MODERN_OFFICE_STYLES,
)
import infinigen_env  # noqa: E402  (sibling: env path detection + persistence)

# --- env -------------------------------------------------------------------

DEFAULT_INFINIGEN_DIR = Path.home() / "module" / "infinigen"
DEFAULT_INFINIGEN_PYTHON = Path.home() / "miniconda3" / "envs" / "infinigen" / "bin" / "python"
DENSITY_FLOATING = {"model_house": 8, "normal_lived_in": 18, "family_home": 28, "storage_heavy": 40}
SURFACE_CLUTTER_FLOATING = {"low": 8, "balanced": 18, "rich": 28, "storage": 40}


def infinigen_dir() -> Path:
    if os.environ.get("INFINIGEN_DIR"):
        return Path(os.environ["INFINIGEN_DIR"]).expanduser()
    return infinigen_env.resolve_dir() or DEFAULT_INFINIGEN_DIR


def infinigen_python() -> Path:
    if os.environ.get("INFINIGEN_PYTHON"):
        return Path(os.environ["INFINIGEN_PYTHON"]).expanduser()
    try:
        return infinigen_env.resolve_python(persist=True)
    except FileNotFoundError:
        return DEFAULT_INFINIGEN_PYTHON


# --- floor plans -----------------------------------------------------------
# Builders return the Infinigen floor-plan dict. `shape` values are emitted as
# STRINGS ("shapely.box(...)") because the .json dispatch eval()s them. Room names
# follow "<type>_<level>/<id>".


def _kr_glasswall_demo(seed: int) -> dict:
    """Clean KR open-LDK 2-room demonstrator: living room + kitchen joined by ONE
    open connection (no door fragmenting the shared wall), a single unit entrance
    on the kitchen exterior, and a panoramic living-room window (통창, verified
    ~3m floor-to-ceiling). Two axis-aligned boxes sharing the full x=0 edge keeps
    the topology simple (lower solve-failure risk than a polygon w/ diagonal).

    Layout (x right, y up; shared wall at x=0):

        kitchen           living-room
        x[-3,0] y[0,4.5]  x[0,6] y[0,4.5]
        ┌────────┐╎┌──────────────┐
        │        │ │              ║   ← 통창 (east wall, panoramic)
        │ entrance│ open          ║
        │  door  │ LDK            ║
        └──win───┘╎└──────────────┘
    """
    return {
        "rooms": {
            "living-room_0/0": {"shape": "shapely.box(0,0,6,4.5)"},
            "kitchen_0/0": {"shape": "shapely.box(-3,0,0,4.5)"},
        },
        # Single unit entrance on the kitchen's exterior (west) wall.
        "doors": {"door": {"shape": "shapely.LineString([(-3,1.5),(-3,2.8)])"}},
        # ONE wide open LDK connection on the shared wall — no door, no interior
        # fragment (that combo is what made the previous wall look "demolished but
        # has a pointless door").
        "opens": {"open": {"shape": "shapely.LineString([(0,1.0),(0,3.5)])"}},
        "interiors": {},
        "windows": {
            # Living-room exterior (east) wall → panoramic = floor-to-ceiling 통창.
            "window": {"shape": "shapely.LineString([(6,0.5),(6,4.0)])", "is_panoramic": 1},
            # Small kitchen window on the south exterior wall.
            "window.001": {"shape": "shapely.LineString([(-2.5,0),(-1.5,0)])"},
        },
    }


def _kr_apt_84(seed: int) -> dict:
    """84㎡-feel corridor-centered KR apartment: 7 rooms tiling a 9×9 footprint, so
    the nav graph has real structure (a hallway threading bedrooms/bath + an open
    LDK), not one big room. Rooms are axis-aligned boxes sharing full edges; every
    door/open/window LineString lies exactly on a shared or exterior wall edge.

        y9 ┌─ bed0 ──┬─ bed1 ─┬─ bath ─┐
           │ (0-3.5) │(3.5-6.5)│(6.5-9)│
        y6.2├──────── hallway ─────────┤   ← 1.2m corridor, doors to every room
        y5 ├── living ───┬─ dining ────┤
           │  (0-5,0-5)  ├──open LDK───┤
        y3 │             ┝━ kitchen ━━━┥   ← kitchen/dining open
        y0 └──통창(panoramic)──┴── win ─┘
            x0          x5            x9
    """
    return {
        "rooms": {
            "living-room_0/0": {"shape": "shapely.box(0,0,5,5)"},
            "kitchen_0/0": {"shape": "shapely.box(5,0,9,3)"},
            "dining-room_0/0": {"shape": "shapely.box(5,3,9,5)"},
            "hallway_0/0": {"shape": "shapely.box(0,5,9,6.2)"},
            "bedroom_0/0": {"shape": "shapely.box(0,6.2,3.5,9)"},
            "bedroom_0/1": {"shape": "shapely.box(3.5,6.2,6.5,9)"},
            "bathroom_0/0": {"shape": "shapely.box(6.5,6.2,9,9)"},
        },
        "doors": {
            # unit entrance on the hallway's west exterior wall
            "door": {"shape": "shapely.LineString([(0,5.3),(0,6.1)])"},
            # hallway ↔ rooms (each on the hallway's shared edge)
            "door.001": {"shape": "shapely.LineString([(2,5),(3,5)])"},          # living
            "door.002": {"shape": "shapely.LineString([(6,5),(7,5)])"},          # dining
            "door.003": {"shape": "shapely.LineString([(1,6.2),(2,6.2)])"},      # bed0
            "door.004": {"shape": "shapely.LineString([(4.5,6.2),(5.5,6.2)])"},  # bed1
            "door.005": {"shape": "shapely.LineString([(7,6.2),(8,6.2)])"},      # bath
        },
        "opens": {
            # open LDK: living↔dining (x=5) and kitchen↔dining (y=3)
            "open": {"shape": "shapely.LineString([(5,3.2),(5,4.8)])"},
            "open.001": {"shape": "shapely.LineString([(5.5,3),(8.5,3)])"},
        },
        "interiors": {},
        "windows": {
            # living-room south exterior wall → panoramic 통창
            "window": {"shape": "shapely.LineString([(0.5,0),(4.5,0)])", "is_panoramic": 1},
            "window.001": {"shape": "shapely.LineString([(6,0),(7,0)])"},        # kitchen
            "window.002": {"shape": "shapely.LineString([(1,9),(2.5,9)])"},      # bed0
            "window.003": {"shape": "shapely.LineString([(4,9),(5.5,9)])"},      # bed1
            "window.004": {"shape": "shapely.LineString([(7.5,9),(8.2,9)])"},    # bath
        },
    }


# Seed-driven procedural generators (see floorplan_gen.py). Unlike the anchors,
# these honor the seed: every seed yields a different VALID wall layout.
def _gen_apartment(seed: int) -> dict:
    return build_floor_plan(int(seed), "apartment")


def _gen_office(seed: int) -> dict:
    return build_floor_plan(int(seed), "office")


def _gen_office_modern_hybrid_v1(seed: int) -> dict:
    return build_floor_plan(int(seed), MODERN_OFFICE_ARCHETYPE)


# key -> builder
FLOOR_PLANS = {
    "kr_apt_84": _kr_apt_84,
    "kr_glasswall_demo": _kr_glasswall_demo,
    "gen_apartment": _gen_apartment,
    # Legacy corridor office retained solely so previously published seed/output
    # provenance can still be regenerated.
    "gen_office": _gen_office,
    "gen_office_modern_hybrid_v1": _gen_office_modern_hybrid_v1,
    # Handled specially because it needs the explicit --room-type argument.
    "single_room": None,
}


# --- seed encoding ---------------------------------------------------------


@dataclass
class AptPreset:
    seed: int
    unit_type: str
    floor_plan_key: str
    density: str
    num_floating: int
    camera_profile: str
    archetype: str | None = None
    room_type: str | None = None
    overrides: list[str] = field(default_factory=list)


def parse_seed(seed: int) -> AptPreset:
    """Decode AABBCCDD -> preset. AA=unit type, BB=layout variant,
    CC=furnishing density, DD=camera/lighting variant."""
    s = f"{int(seed):08d}"
    aa, bb, cc, dd = int(s[0:2]), int(s[2:4]), int(s[4:6]), int(s[6:8])

    if aa in (10, 11):
        unit_type = "59m2"
    elif aa in (20, 21):
        unit_type = "84m2"
    elif aa == 30:
        unit_type = "officetel"
    else:
        unit_type = "84m2"

    # BB (layout variant) now selects between hand-authored anchors and the
    # seed-driven procedural generators (floorplan_gen.py):
    #   BB == 0        -> anchor by unit_type (back-compat; canonical fixed layout)
    #   1  <= BB <= 49 -> generated apartment (living-centered, corridor, LDK)
    #   50 <= BB <= 99 -> generated office (corridor network, dozens of rooms)
    archetype: str | None = None
    if bb == 0:
        floor_plan_key = "kr_apt_84" if unit_type == "84m2" else "kr_glasswall_demo"
    elif bb < 50:
        floor_plan_key, archetype = "gen_apartment", "apartment"
    else:
        floor_plan_key, archetype = "gen_office", "office"

    if cc < 25:
        density, num_floating = "model_house", 8
    elif cc < 50:
        density, num_floating = "normal_lived_in", 18
    elif cc < 75:
        density, num_floating = "family_home", 28
    else:
        density, num_floating = "storage_heavy", 40

    camera_profile = (
        "daytime_living_room" if dd < 20 else
        "evening_warm_light" if dd < 40 else
        "entrance_hallway" if dd < 60 else
        "kitchen_to_living" if dd < 80 else
        "robot_low_cam"
    )
    return AptPreset(
        seed=int(seed), unit_type=unit_type, floor_plan_key=floor_plan_key,
        density=density, num_floating=num_floating, camera_profile=camera_profile,
        archetype=archetype,
    )


# --- command construction --------------------------------------------------


def build_command(preset: AptPreset, *, out: Path, stage: str, fast: bool,
                  floor_plan_json: Path, extra_overrides: list[str]) -> list[str]:
    """stage: 'layout' (no objects, fast wall/cutter check) | 'full' (object solve)."""
    if stage == "layout":
        configs = ["no_objects.gin", "overhead.gin"]
    else:
        configs = (["fast_solve.gin"] if fast else []) + ["overhead.gin"]

    overrides = [
        "compose_indoors.terrain_enabled=False",
        # The long-lived FCL broad-phase managers used by the solver's BVH
        # cache reproducibly segfault in python-fcl 0.7.0.8 after roughly 150
        # annealing iterations on this deployment.  Disabling the cache keeps
        # the collision constraints themselves enabled, but rebuilds managers
        # instead of reusing native CollisionObjects across scene mutations.
        "bvh_caching_config.enabled=False",
        # absolute path so cwd (the install dir) doesn't matter
        f"Solver.floor_plan='{floor_plan_json}'",
    ]
    if preset.floor_plan_key == "single_room":
        # Keep the generated asset light. The room itself owns the window
        # opening; outdoor context is injected later by the Mitsuba envmap.
        overrides.append("home_room_constraints.has_fewer_rooms=True")
    if stage == "full":
        overrides += [
            "compose_indoors.invisible_room_ceilings_enabled=True",
            "compose_indoors.floating_objs_enabled=True",
            f"compose_indoors.num_floating={preset.num_floating}",
            # Floating-object placement is a later, optional clutter pass and
            # uses the same unstable native FCL binding.  Keep it enabled but
            # avoid its extra FCL collision-manager calls by default.
            "compose_indoors.enable_collision_floating=False",
            "compose_indoors.enable_collision_solved=False",
        ]
    overrides += extra_overrides

    py = str(infinigen_python())
    safe_entry = Path(__file__).resolve().with_name("infinigen_generate_indoors_safe.py")
    cmd = [py, str(safe_entry),
           "-s", str(preset.seed), "--task", "coarse",
           "--output_folder", str(out), "-g", *configs, "-p", *overrides]
    return cmd


def main() -> int:
    ap = argparse.ArgumentParser(description="Generate Infinigen indoor scenes.")
    ap.add_argument("--seed", type=int, required=True, help="8-digit AABBCCDD seed.")
    ap.add_argument("--stage", choices=["layout", "full"], default="layout",
                    help="layout = no-objects wall/cutter check (fast); full = object solve.")
    ap.add_argument("--fast", action="store_true",
                    help="full stage only: use fast_solve.gin (faster, lower placement quality).")
    ap.add_argument("--out", type=Path, default=None,
                    help="Output folder (default: data/infinigen_generated/outputs/kr_<seed>/<stage>).")
    ap.add_argument("--floor-plan", default=None,
                    help=f"Override floor-plan key. Available: {', '.join(FLOOR_PLANS)}")
    ap.add_argument("--room-type", choices=SINGLE_ROOM_TYPES, default="living-room",
                    help="Single-room semantic type (all Infinigen room semantics supported).")
    ap.add_argument("--density", choices=tuple(DENSITY_FLOATING), default=None,
                    help="Explicit furnishing provenance; overrides density encoded in the seed.")
    ap.add_argument("--logical-seed", default=None, help="User-facing seed retained in provenance metadata.")
    ap.add_argument("--variation-id", type=int, default=0)
    ap.add_argument("--anchor-richness", choices=("minimal", "balanced", "rich", "storage"), default="balanced")
    ap.add_argument("--surface-clutter", choices=("low", "balanced", "rich", "storage"), default="balanced")
    ap.add_argument("--office-style", choices=MODERN_OFFICE_STYLES, default="modern_basic_v1",
                    help="Modern Office visual/structural preset (office archetype only).")
    ap.add_argument("--graph-max-nodes", type=int, default=70)
    ap.add_argument("--graph-heading-count", type=int, default=24)
    ap.add_argument("--graph-min-node-spacing", type=float, default=0.25)
    ap.add_argument("--graph-robot-radius", type=float, default=0.30)
    ap.add_argument("-p", "--override", action="append", default=[],
                    help="Extra raw gin override (repeatable), e.g. -p compose_indoors.num_floating=12")
    ap.add_argument("--run", action="store_true",
                    help="Actually launch Infinigen (default: print the command only).")
    args = ap.parse_args()

    preset = parse_seed(args.seed)
    if args.density:
        preset.density = args.density
        preset.num_floating = DENSITY_FLOATING[args.density]
    preset.num_floating = SURFACE_CLUTTER_FLOATING[args.surface_clutter]
    if args.floor_plan:
        if args.floor_plan not in FLOOR_PLANS:
            ap.error(f"unknown floor plan {args.floor_plan!r}; have {list(FLOOR_PLANS)}")
        preset.floor_plan_key = args.floor_plan
        preset.archetype = {"gen_apartment": "apartment",
                            "gen_office": "office",
                            "gen_office_modern_hybrid_v1": "office",
                            "single_room": "single_room"}.get(args.floor_plan)
    if preset.floor_plan_key == "single_room":
        preset.room_type = args.room_type.replace("_", "-")

    repo_root = Path(__file__).resolve().parent.parent
    room_suffix = f"_single_room_{preset.room_type.replace('-', '_')}" if preset.floor_plan_key == "single_room" else ""
    out = args.out or (repo_root / "data" / "infinigen_generated" / "outputs"
                       / f"kr_{args.seed}{room_suffix}" / args.stage)
    out.mkdir(parents=True, exist_ok=True)

    # Emit the floor plan as JSON (the most robust way to hand it to Solver).
    floor_plan = (build_single_room_plan(args.seed, preset.room_type or args.room_type)
                  if preset.floor_plan_key == "single_room"
                  else FLOOR_PLANS[preset.floor_plan_key](args.seed))
    floor_plan_json = (out / "floor_plan.json").resolve()
    floor_plan_json.write_text(json.dumps(floor_plan, indent=2), encoding="utf-8")

    # Record the decoded preset (camera profile etc. are metadata-only for now).
    office_style = args.office_style if preset.floor_plan_key == "gen_office_modern_hybrid_v1" else None
    office_manifest = None
    if office_style == "modern_glass_v1":
        # Validate before launching Blender so an unsatisfiable topology has a
        # clean layout error rather than a late geometry fallback.
        office_manifest = modern_office_partition_spec(args.seed)
    office_style_digest = (office_manifest or {}).get(
        "digest", hashlib.sha256(str(office_style or "").encode("utf-8")).hexdigest()
    )
    (out / "kr_preset.json").write_text(json.dumps({
        "seed": preset.seed, "unit_type": preset.unit_type,
        "logical_seed": str(args.logical_seed or f"{args.seed:08d}"), "effective_scene_seed": preset.seed,
        "variation_id": args.variation_id, "content_policy_version": "room-content-v1",
        "anchor_richness": args.anchor_richness, "surface_clutter": args.surface_clutter,
        "floor_plan_key": preset.floor_plan_key, "archetype": preset.archetype,
        "density": preset.density,
        "num_floating": preset.num_floating, "camera_profile": preset.camera_profile,
        "scene_mode": "single_room" if preset.floor_plan_key == "single_room" else "multi_room",
        "room_type": preset.room_type,
        "outdoor_context": "environment_map_pending",
        "terrain_enabled": False,
        "window_policy": "required",
        "opticalnav_graph_profile": {
            "max_nodes": args.graph_max_nodes,
            "heading_count": args.graph_heading_count,
            "min_node_spacing_m": args.graph_min_node_spacing,
            "robot_radius_m": args.graph_robot_radius,
        },
        **({"office_profile": {**modern_office_metadata(args.seed), "office_style": office_style,
                                "office_style_digest": office_style_digest}}
           if preset.floor_plan_key == "gen_office_modern_hybrid_v1" else {}),
    }, indent=2), encoding="utf-8")

    if preset.floor_plan_key == "gen_office_modern_hybrid_v1":
        (out / "office_layout_manifest.json").write_text(json.dumps({
            "schema": "robomituba.opticalnav_office_layout.v1",
            "profile": MODERN_OFFICE_PROFILE,
            "source_floor_plan": "floor_plan.json",
            "office_style": office_style,
            "office_style_digest": office_style_digest,
            "structural_glass": office_manifest,
            **modern_office_metadata(args.seed),
        }, indent=2), encoding="utf-8")

    cmd = build_command(preset, out=out, stage=args.stage, fast=args.fast,
                        floor_plan_json=floor_plan_json, extra_overrides=args.override)

    idir = infinigen_dir()
    print(f"# preset: {preset.unit_type} / {preset.floor_plan_key}"
          f"{('/' + str(preset.room_type)) if preset.room_type else ''} / density={preset.density}"
          f" (num_floating={preset.num_floating}) / camera={preset.camera_profile}")
    print(f"# INFINIGEN_DIR = {idir}")
    print(f"# floor_plan    = {floor_plan_json}")
    print(f"# output_folder = {out}")
    print(f"# (cd {idir} && \\\n#   " + " ".join(cmd) + ")")

    if not args.run:
        print("\n# dry-run (pass --run to launch). Tip: run --stage layout first to verify walls.")
        return 0

    if not infinigen_python().exists():
        print(f"ERROR: infinigen python not found: {infinigen_python()}", file=sys.stderr)
        return 2
    if not idir.exists():
        print(f"ERROR: INFINIGEN_DIR not found: {idir}", file=sys.stderr)
        return 2

    env = {**os.environ, "PYTHONUNBUFFERED": "1",
           "ROBOMITUBA_INFINIGEN_ROOM_TYPE": str(preset.room_type or ""),
           "ROBOMITUBA_INFINIGEN_PROGRAM": (
               "modern_office" if preset.floor_plan_key == "gen_office_modern_hybrid_v1" else ""
           ),
           "ROBOMITUBA_INFINIGEN_ANCHOR_RICHNESS": args.anchor_richness}
    if office_style:
        env["ROBOMITUBA_INFINIGEN_OFFICE_STYLE"] = office_style
        env["ROBOMITUBA_INFINIGEN_OFFICE_MANIFEST"] = str(out / "office_layout_manifest.json")
    proc = subprocess.run(cmd, cwd=str(idir), env=env)
    if proc.returncode < 0:
        signal_number = -int(proc.returncode)
        try:
            import signal
            signal_name = signal.Signals(signal_number).name
        except (ValueError, AttributeError):
            signal_name = "unknown signal"
        print(
            f"ERROR: Infinigen terminated by {signal_name} ({signal_number})",
            file=sys.stderr,
        )
        # Preserve the conventional shell representation (SIGSEGV -> 139)
        # instead of letting the nested Python wrapper turn -11 into 245.
        return 128 + signal_number
    return proc.returncode


if __name__ == "__main__":
    raise SystemExit(main())
