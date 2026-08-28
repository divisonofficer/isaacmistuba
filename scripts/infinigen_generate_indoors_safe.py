#!/usr/bin/env python3
"""Run Infinigen Indoors with its non-FCL accessibility cost implementation.

Infinigen 1.19.1 evaluates accessibility by colliding temporary boxes against
triangle meshes through python-fcl by default.  On the deployed python-fcl
0.7.0.8 wheel this reproducibly segfaults inside
``ShapeTransformedTriangleIntersectIndepImpl<Box>`` during long annealing runs.
Infinigen already ships a centroid-based accessibility implementation selected
by ``use_collision_impl=False``.  Patch only that evaluator registration before
executing the normal module; placement collision constraints remain intact.
"""

from __future__ import annotations

import runpy
import bpy

from infinigen.core.constraints import constraint_language as cl
from infinigen.core.constraints.evaluator.node_impl import impl_bindings
from infinigen.core.util import blender as butil
from infinigen.assets.composition import material_assignments
from infinigen.assets.materials import ceramic
from infinigen.assets.materials.ceramic.concrete import Concrete
from infinigen_compat import (
    install_callable_floor_material_compat,
    install_concrete_wall_hint_compat,
    install_idempotent_collection_delete_compat,
)
from infinigen_room_programs import room_content_program
import os
import sys
from pathlib import Path

office_style = os.environ.get("ROBOMITUBA_INFINIGEN_OFFICE_STYLE", "")
office_manifest = os.environ.get("ROBOMITUBA_INFINIGEN_OFFICE_MANIFEST", "")
if office_style:
    from infinigen_modern_office_style import install_door_bias
    install_door_bias(office_style)


def _safe_accessibility_impl(cons, state, child_vals):
    return impl_bindings.accessibility_impl(
        cons, state, child_vals, use_collision_impl=False,
    )


impl_bindings.node_impls[cl.accessibility_cost] = _safe_accessibility_impl


# Infinigen's room decorator sends tile-layout hints to every selected wall
# material.  Concrete.generate() in the deployed 1.19.1 tree predates that
# calling convention and accepts no keywords, so garage/warehouse generation
# fails whenever Concrete is sampled for a wall.  Concrete is coordinate-based
# and has no tile orientation/layout to configure; discarding only these known
# decorator hints preserves its authored shader while keeping unexpected
# arguments strict.
install_concrete_wall_hint_compat(Concrete)
repaired_utility_floor_entries = install_callable_floor_material_compat(material_assignments, ceramic)
install_idempotent_collection_delete_compat(butil, bpy)
with room_content_program(
    os.environ.get("ROBOMITUBA_INFINIGEN_ROOM_TYPE", ""),
    os.environ.get("ROBOMITUBA_INFINIGEN_ANCHOR_RICHNESS", "balanced"),
    os.environ.get("ROBOMITUBA_INFINIGEN_PROGRAM", ""),
    os.environ.get("ROBOMITUBA_INFINIGEN_PLACEMENT_PROFILE", "legacy_clutter_v1"),
) as room_program:
    print(
        "[robomituba] FCL box/triangle accessibility disabled; "
        "using Infinigen centroid approximation; Concrete wall hints compatible; "
        f"utility-floor callable repairs={repaired_utility_floor_entries}; "
        f"temporary collection cleanup idempotent; room content program={room_program}",
        flush=True,
    )
    runpy.run_module("infinigen_examples.generate_indoors", run_name="__main__")

if office_style:
    if not office_manifest:
        raise RuntimeError("modern office style requested without office layout manifest")
    output_folder = Path(sys.argv[sys.argv.index("--output_folder") + 1])
    if office_style == "modern_glass_v2":
        # Keep workstation pairing outside the Infinigen hard solver graph.
        # The resulting mapping is an input to population audit/publish, not a
        # cosmetic best-effort adjustment.
        from infinigen_office_workstations import apply_office_workstation_layout
        workstation = apply_office_workstation_layout(office_manifest, output_folder)
        print(
            "[robomituba] office workstation layout applied: "
            f"pairs={len(workstation['mappings'])} digest={workstation['layout_digest']}",
            flush=True,
        )
    from infinigen_modern_office_style import apply_office_style
    result = apply_office_style(office_manifest, office_style)
    bpy.ops.wm.save_as_mainfile(filepath=str(output_folder / "scene.blend"))
    print(f"[robomituba] modern office style applied: {result}", flush=True)
