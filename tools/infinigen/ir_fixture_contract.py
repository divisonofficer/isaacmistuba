"""Deterministic per-fixture subset selection for a lighting condition.

`view_plan` runs at STAGES index 11 and `principled_prepare` at 18, so the
render plan is built before the prepared blend exists and cannot enumerate the
fixtures it wants switched.  The plan therefore carries a *specification* and
the worker resolves it, which only works if resolution is a pure function.

It is hash-derived per fixture rather than drawn from an RNG stream, so adding
or removing one fixture cannot flip the state of any other -- an RNG whose draw
order depends on the inventory would silently repaint a scene whenever its light
set changed.

Pure Python and dependency-free so the Blender worker can import it directly,
matching how ``ir_worker_aov_contract`` is used.
"""
from __future__ import annotations

import hashlib
from typing import Any, Iterable, Mapping, Sequence

FIXTURE_SUBSET_SAMPLER_VERSION = "fixture-subset-hash-v1"
#: Kelvin jitter is quantised before conversion: an unquantised float would let
#: interpreter-level rounding differences move a recipe digest.
KELVIN_QUANTUM = 25.0


def _unit(*parts: Any) -> float:
    digest = hashlib.sha256("|".join(str(p) for p in parts).encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") / 2 ** 64


def resolve_fixture_subset(
    fixtures: Sequence[Mapping[str, Any]],
    spec: Mapping[str, Any] | None,
    *,
    scene_id: str,
    condition_id: str,
    rig_digest: str,
    blackbody: Any = None,
) -> dict[str, Any]:
    """Resolve which fixtures are on, and at what tint and scale.

    ``blackbody`` is injected rather than imported so this module stays free of
    the navigation_dataset dependency; the caller passes
    ``ir_indoor_fixtures.blackbody_linear_rgb``.
    """
    if not spec:
        return {"applied": False, "on": [], "off": [], "forced_on": [], "fixtures": {}}
    groups = dict(spec.get("groups") or {})
    seed = spec.get("subset_seed", 0)
    salt = spec.get("subset_salt", "")
    minimum = int(spec.get("min_on_per_room", 0))

    resolved: dict[str, dict[str, Any]] = {}
    draws: dict[str, float] = {}
    for fixture in fixtures:
        fid = str(fixture.get("fixture_id") or "")
        group = str(fixture.get("group") or "")
        rule = groups.get(group)
        if not fid or rule is None:
            # A group the condition says nothing about keeps whatever the
            # prepared blend set, rather than being implicitly switched off.
            continue
        base = (FIXTURE_SUBSET_SAMPLER_VERSION, scene_id, condition_id, salt, rig_digest, fid, seed)
        draw = _unit(*base)
        draws[fid] = draw
        on = draw < float(rule.get("on_probability", 1.0))
        kelvin = rule.get("color_temperature_k")
        colour = None
        if kelvin is not None and blackbody is not None:
            jitter = float(rule.get("color_temperature_jitter_k", 0.0) or 0.0)
            spread = _unit(*base, "color")
            value = float(kelvin) - jitter + 2.0 * jitter * spread
            quantised = round(value / KELVIN_QUANTUM) * KELVIN_QUANTUM
            colour = list(blackbody(quantised))
            kelvin = quantised
        resolved[fid] = {
            "group": group,
            "room_id": str(fixture.get("room_id") or ""),
            "on": bool(on),
            "energy_scale": float(rule.get("energy_scale", 1.0)),
            "color_temperature_k": kelvin,
            "color_linear_rgb": colour,
            "forced_on": False,
        }

    # A room that draws every one of its switchable fixtures off would render
    # black for no stated reason; repair it deterministically by turning on the
    # fixture with the smallest draw.
    forced: list[str] = []
    if minimum > 0:
        by_room: dict[str, list[str]] = {}
        # Every governed fixture is a repair candidate, including one whose group
        # drew a zero probability.  The floor exists to stop a room rendering
        # black; a condition that genuinely wants darkness omits the floor
        # rather than relying on a probability of zero to defeat it.
        for fid, row in resolved.items():
            by_room.setdefault(row["room_id"], []).append(fid)
        for room, ids in sorted(by_room.items()):
            if sum(resolved[f]["on"] for f in ids) >= minimum:
                continue
            for fid in sorted(ids, key=lambda f: (draws[f], f))[:minimum]:
                if not resolved[fid]["on"]:
                    resolved[fid]["on"] = True
                    resolved[fid]["forced_on"] = True
                    forced.append(fid)
    return {
        "applied": True,
        "sampler_version": FIXTURE_SUBSET_SAMPLER_VERSION,
        "on": sorted(f for f, r in resolved.items() if r["on"]),
        "off": sorted(f for f, r in resolved.items() if not r["on"]),
        "forced_on": sorted(forced),
        "fixtures": resolved,
    }


__all__ = ["FIXTURE_SUBSET_SAMPLER_VERSION", "KELVIN_QUANTUM", "resolve_fixture_subset"]
