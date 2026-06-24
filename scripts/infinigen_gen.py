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
curtain/shutter (WindowFactory is not @gin.configurable), per-room material bias,
camera profile placement. The seed's camera digits are recorded in metadata only.

This script does not run Infinigen itself unless asked; default is --dry-run-safe:
it always prints the exact command. Use --run to actually launch (heavy: needs the
conda env + Blender + GPU).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

# --- env -------------------------------------------------------------------

DEFAULT_INFINIGEN_DIR = Path.home() / "module" / "infinigen"
DEFAULT_INFINIGEN_PYTHON = Path.home() / "miniconda3" / "envs" / "infinigen" / "bin" / "python"


def infinigen_dir() -> Path:
    return Path(os.environ.get("INFINIGEN_DIR", str(DEFAULT_INFINIGEN_DIR))).expanduser()


def infinigen_python() -> Path:
    return Path(os.environ.get("INFINIGEN_PYTHON", str(DEFAULT_INFINIGEN_PYTHON))).expanduser()


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


# key -> builder
FLOOR_PLANS = {
    "kr_apt_84": _kr_apt_84,
    "kr_glasswall_demo": _kr_glasswall_demo,
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

    # 84㎡ → multi-room corridor layout (nav-friendly); others fall back to the
    # simple open-LDK demonstrator until more layouts are authored.
    floor_plan_key = "kr_apt_84" if unit_type == "84m2" else "kr_glasswall_demo"

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
        # absolute path so cwd (the install dir) doesn't matter
        f"Solver.floor_plan='{floor_plan_json}'",
    ]
    if stage == "full":
        overrides += [
            "compose_indoors.invisible_room_ceilings_enabled=True",
            "compose_indoors.floating_objs_enabled=True",
            f"compose_indoors.num_floating={preset.num_floating}",
            "compose_indoors.enable_collision_floating=True",
            "compose_indoors.enable_collision_solved=True",
        ]
    overrides += extra_overrides

    py = str(infinigen_python())
    cmd = [py, "-m", "infinigen_examples.generate_indoors",
           "-s", str(preset.seed), "--task", "coarse",
           "--output_folder", str(out), "-g", *configs, "-p", *overrides]
    return cmd


def main() -> int:
    ap = argparse.ArgumentParser(description="Generate Korean-apartment Infinigen scenes.")
    ap.add_argument("--seed", type=int, required=True, help="8-digit AABBCCDD seed.")
    ap.add_argument("--stage", choices=["layout", "full"], default="layout",
                    help="layout = no-objects wall/cutter check (fast); full = object solve.")
    ap.add_argument("--fast", action="store_true",
                    help="full stage only: use fast_solve.gin (faster, lower placement quality).")
    ap.add_argument("--out", type=Path, default=None,
                    help="Output folder (default: data/infinigen_generated/outputs/kr_<seed>/<stage>).")
    ap.add_argument("--floor-plan", default=None,
                    help=f"Override floor-plan key. Available: {', '.join(FLOOR_PLANS)}")
    ap.add_argument("-p", "--override", action="append", default=[],
                    help="Extra raw gin override (repeatable), e.g. -p compose_indoors.num_floating=12")
    ap.add_argument("--run", action="store_true",
                    help="Actually launch Infinigen (default: print the command only).")
    args = ap.parse_args()

    preset = parse_seed(args.seed)
    if args.floor_plan:
        if args.floor_plan not in FLOOR_PLANS:
            ap.error(f"unknown floor plan {args.floor_plan!r}; have {list(FLOOR_PLANS)}")
        preset.floor_plan_key = args.floor_plan

    repo_root = Path(__file__).resolve().parent.parent
    out = args.out or (repo_root / "data" / "infinigen_generated" / "outputs"
                       / f"kr_{args.seed}" / args.stage)
    out.mkdir(parents=True, exist_ok=True)

    # Emit the floor plan as JSON (the most robust way to hand it to Solver).
    floor_plan = FLOOR_PLANS[preset.floor_plan_key](args.seed)
    floor_plan_json = (out / "floor_plan.json").resolve()
    floor_plan_json.write_text(json.dumps(floor_plan, indent=2), encoding="utf-8")

    # Record the decoded preset (camera profile etc. are metadata-only for now).
    (out / "kr_preset.json").write_text(json.dumps({
        "seed": preset.seed, "unit_type": preset.unit_type,
        "floor_plan_key": preset.floor_plan_key, "density": preset.density,
        "num_floating": preset.num_floating, "camera_profile": preset.camera_profile,
    }, indent=2), encoding="utf-8")

    cmd = build_command(preset, out=out, stage=args.stage, fast=args.fast,
                        floor_plan_json=floor_plan_json, extra_overrides=args.override)

    idir = infinigen_dir()
    print(f"# preset: {preset.unit_type} / {preset.floor_plan_key} / density={preset.density}"
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

    env = {**os.environ, "PYTHONUNBUFFERED": "1"}
    proc = subprocess.run(cmd, cwd=str(idir), env=env)
    return proc.returncode


if __name__ == "__main__":
    raise SystemExit(main())
