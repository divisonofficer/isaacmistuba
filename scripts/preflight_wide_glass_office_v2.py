#!/usr/bin/env python3
"""Cheap, no-render preflight for the wide glass office v2 generator.

This is deliberately executed with the Infinigen Python environment before a
wizard starts any expensive full candidates.  It exercises the exact solver
registry lookups that otherwise fail only after ``solve_rooms`` completes.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO = Path(__file__).resolve().parent.parent
if str(REPO / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO / "scripts"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, required=True)
    args = parser.parse_args(argv)

    from floorplan_gen import (
        WIDE_GLASS_OFFICE_ARCHETYPE,
        build_floor_plan,
        validate_plan,
        wide_glass_office_metadata,
        wide_glass_office_partition_spec,
    )
    from infinigen.core.constraints import checks, usage_lookup
    from infinigen.core.constraints.example_solver.moves.addition import sample_rand_placeholder
    from infinigen.core.tags import Semantics
    from infinigen_examples.generate_indoors import all_vars, default_greedy_stages
    from infinigen_room_programs import (
        office_asset_usage,
        office_furniture_constraints,
        validate_office_asset_usage,
    )

    plan = build_floor_plan(args.seed, WIDE_GLASS_OFFICE_ARCHETYPE)
    errors = validate_plan(plan)
    if errors:
        raise ValueError("invalid office v2 floor plan: " + "; ".join(errors))
    metadata = wide_glass_office_metadata(args.seed)
    spec = wide_glass_office_partition_spec(args.seed)
    if not 400 <= float(metadata["footprint_area_m2"]) <= 550:
        raise ValueError("office v2 footprint is outside 400–550m²")
    if not 3 <= int(metadata["work_bay_count"]) <= 4 or max(metadata["work_bay_area_m2"]) > 75:
        raise ValueError("office v2 work-bay contract failed")
    if len(spec["segments"]) != 10 or int(spec["requested_pane_count"]) != 20:
        raise ValueError("office v2 glass partition contract failed")
    for segment in spec["segments"]:
        owners = segment.get("opaque_wall_owners")
        if owners != [segment.get("room"), segment.get("corridor")]:
            raise ValueError(f"office v2 glass owner contract failed: {segment.get('segment_id')}")

    usage = office_asset_usage()
    validate_office_asset_usage(usage)
    usage_lookup.initialize_from_dict(usage)
    queried_tags = (
        Semantics.SingleGenerator,
        Semantics.RealPlaceholder,
        Semantics.AssetAsPlaceholder,
        Semantics.PlaceholderBBox,
        Semantics.AssetPlaceholderForChildren,
    )
    for factory in usage[Semantics.Object]:
        for tag in queried_tags:
            usage_lookup.has_usage(factory, tag)
    # Registry entries can still point to a factory whose placeholder API is
    # incompatible with this Infinigen build. Create one throw-away placeholder
    # per allowed factory now; the short-lived preflight interpreter exits
    # immediately afterwards and never saves these meshes.
    placeholder_factories = []
    for factory in sorted(usage[Semantics.Object], key=lambda item: item.__name__):
        sample_rand_placeholder(factory)
        placeholder_factories.append(factory.__name__)
    problem = office_furniture_constraints(2)
    checks.check_all(problem, default_greedy_stages(), all_vars)
    print(json.dumps({
        "status": "passed",
        "profile": metadata["profile"],
        "footprint_area_m2": metadata["footprint_area_m2"],
        "work_bays": metadata["work_bay_count"],
        "solver_constraint_count": len(problem.constraints),
        "placeholder_factories": placeholder_factories,
        "partitions": len(spec["segments"]),
        "panes": spec["requested_pane_count"],
    }, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
