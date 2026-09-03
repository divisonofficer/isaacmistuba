"""Choose structural surface finishes on purpose instead of by accident.

The room shell -- walls, floor, ceiling -- is 62% of an average frame, so its
roughness decides whether a scene carries a specular cue at all.  Nothing
controlled it: ``bindings_for_scene`` drew uniformly from whatever the registry
approved for the role, and the measured corpus came out bimodal.  Of 88 rendered
scenes, 81 had a shell less than 1% smooth and 6 were over 90% smooth; exactly
one landed in between.

The registry is not the problem.  Its 100 materials split 15 glossy / 53 mid /
32 matte, and both wall and floor have all three within reach.  What was missing
is that a real room does not wear one finish: a floor is often varnished or
tiled, walls are eggshell or satin, and a ceiling is flat.  Drawing every
surface from one pool produces rooms made entirely of chalk or entirely of
polish.

Measured at the pixel level the registry is itself bimodal: 82 of its 100
materials have essentially no pixel smooth enough for a highlight and 13 are
more than half smooth, with almost nothing between.  So a band on mean
roughness cannot work -- the first attempt at one made things worse, cutting
scenes inside the target band from 45% to 8%, because a mean of 0.45 excludes
the glossy materials without admitting anything in their place.

What decides a scene is simply how many of its few shell slots drew one of
those 13.  The policy therefore states, per role, how often that should happen:
a floor is frequently varnished or tiled, walls are occasionally satin, a
ceiling is flat.  That is a budget, not a band, and it controls the outcome
directly.
"""
from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

POLICY_SCHEMA = "robomituba.ir_structural_finish_policy.v1"
POLICY_VERSION = "structural-finish-v1"

#: How often each role should draw a material that can actually hold a
#: highlight.  A floor is the smoothest thing in most rooms, a wall occasionally
#: satin, a ceiling flat.  These are frequencies of real finishes, not a knob
#: turned until the specular numbers looked better.
DEFAULT_SMOOTH_RATE: dict[str, float] = {
    "floor": 0.55,
    "wall": 0.15,
    "column": 0.25,
    "panel": 0.30,
    "ceiling": 0.0,
}
#: A material counts as smooth when this much of its roughness map is at or
#: below SMOOTH_ROUGHNESS.  The registry splits cleanly around it: 13 materials
#: are over half smooth and 82 have almost none, so the exact value barely
#: matters.
MATERIAL_SMOOTH_FRACTION = 0.10
#: Fraction of the shell that should be smooth enough to hold a highlight.  The
#: corpus sits at 0% or 100%; anywhere in here is a room rather than a cave or a
#: hall of mirrors.
SHELL_SMOOTH_TARGET = (0.05, 0.60)
SMOOTH_ROUGHNESS = 0.30


def stable_digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def load_policy(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {"schema": POLICY_SCHEMA, "version": POLICY_VERSION,
                "smooth_rate": dict(DEFAULT_SMOOTH_RATE),
                "material_smooth_fraction": MATERIAL_SMOOTH_FRACTION,
                "shell_smooth_target": list(SHELL_SMOOTH_TARGET),
                "smooth_roughness": SMOOTH_ROUGHNESS}
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if payload.get("schema") != POLICY_SCHEMA:
        raise ValueError(f"structural finish policy schema must be {POLICY_SCHEMA}")
    for role, rate in (payload.get("smooth_rate") or {}).items():
        if not 0.0 <= float(rate) <= 1.0:
            raise ValueError(f"smooth_rate for {role} must be a probability in [0, 1]")
    target = payload.get("shell_smooth_target") or list(SHELL_SMOOTH_TARGET)
    if not (0.0 <= float(target[0]) < float(target[1]) <= 1.0):
        raise ValueError("shell_smooth_target must satisfy 0 <= low < high <= 1")
    return payload


def measure_roughness(path: Path, *, smooth: float = SMOOTH_ROUGHNESS) -> float | None:
    """Fraction of a roughness map at or below ``smooth``, or None if unreadable.

    A fraction rather than a mean: the registry's materials are individually
    near-uniform, so a mean of 0.45 says nothing about whether any of it can
    hold a highlight, while this is directly comparable to what the rendered
    frames report.

    Imported lazily: the policy is pure and testable without an image library,
    and only manifest building needs to touch the map files.
    """
    try:
        import cv2  # noqa: PLC0415
        import numpy as np  # noqa: PLC0415
    except ImportError:
        return None
    image = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if image is None:
        return None
    array = image.astype("float32") / (65535.0 if image.dtype.itemsize == 2 else 255.0)
    if array.ndim == 3:
        array = array.mean(2)
    return float((np.asarray(array) <= smooth).mean())


def roughness_index(registry: Mapping[str, Any], root: Path,
                    *, smooth: float = SMOOTH_ROUGHNESS) -> dict[str, float]:
    """Smooth-pixel fraction per material id, for every map that can be read."""
    index: dict[str, float] = {}
    for record in registry.get("materials") or []:
        relative = (record.get("maps") or {}).get("roughness")
        if not relative:
            continue
        value = measure_roughness(root / relative, smooth=smooth)
        if value is not None:
            index[str(record["id"])] = round(value, 6)
    return index


def smooth_rate_for(policy: Mapping[str, Any], role: str) -> float | None:
    rate = (policy.get("smooth_rate") or {}).get(role)
    return None if rate is None else float(rate)


def choose_for_role(choices: Sequence[Mapping[str, Any]], role: str, rng: random.Random,
                    *, policy: Mapping[str, Any], roughness: Mapping[str, float]) -> Mapping[str, Any]:
    """Pick a material for one structural slot against the role's smooth budget.

    ``roughness`` maps a material id to the fraction of its roughness map that
    can hold a highlight -- a fraction, not a mean, because the registry's
    materials are individually near-uniform and a mean hides which side of the
    split they fall on.

    Whichever pool the draw lands in, an empty one falls through to the full
    approved set: a finish preference must never be the reason a scene cannot
    be rendered.
    """
    rate = smooth_rate_for(policy, role)
    if rate is None:
        return choices[rng.randrange(len(choices))]
    cut = float(policy.get("material_smooth_fraction", MATERIAL_SMOOTH_FRACTION))
    smooth = [c for c in choices if roughness.get(str(c.get("id")), 0.0) >= cut]
    matte = [c for c in choices if roughness.get(str(c.get("id")), 0.0) < cut]
    pool = smooth if (rng.random() < rate and smooth) else (matte or smooth)
    return pool[rng.randrange(len(pool))] if pool else choices[rng.randrange(len(choices))]


def shell_smooth_fraction(bindings: Iterable[Mapping[str, Any]],
                          roughness: Mapping[str, float], *,
                          smooth: float = SMOOTH_ROUGHNESS) -> float | None:
    """Expected share of the shell that can hold a highlight.

    The mean over slots of each material's own smooth fraction, which estimates
    the rendered pixel measurement without needing a render.  Slots are weighted
    equally because their screen area is not known until the camera is placed.
    """
    values = [roughness[str(b.get("material_id"))] for b in bindings
              if str(b.get("material_id")) in roughness]
    if not values:
        return None
    return sum(values) / len(values)


def finish_report(bindings: Sequence[Mapping[str, Any]], roughness: Mapping[str, float],
                  policy: Mapping[str, Any]) -> dict[str, Any]:
    smooth = float(policy.get("smooth_roughness", SMOOTH_ROUGHNESS))
    target = policy.get("shell_smooth_target") or list(SHELL_SMOOTH_TARGET)
    fraction = shell_smooth_fraction(bindings, roughness, smooth=smooth)
    per_role: dict[str, Any] = {}
    for binding in bindings:
        role = str(binding.get("role") or "")
        value = roughness.get(str(binding.get("material_id")))
        if value is None:
            continue
        per_role.setdefault(role, []).append(value)
    report = {
        "schema": POLICY_SCHEMA, "version": POLICY_VERSION,
        "policy_digest": stable_digest(policy),
        "smooth_roughness": smooth,
        "shell_smooth_target": [float(target[0]), float(target[1])],
        "shell_smooth_fraction": None if fraction is None else round(fraction, 4),
        "within_target": None if fraction is None else bool(
            float(target[0]) <= fraction <= float(target[1])),
        "roles": {role: {"slots": len(v), "mean_smooth_fraction": round(sum(v)/len(v), 4),
                         "smooth_slots": sum(1 for x in v if x >= float(
                             policy.get("material_smooth_fraction", MATERIAL_SMOOTH_FRACTION)))}
                  for role, v in sorted(per_role.items())},
    }
    return report


__all__ = [
    "DEFAULT_SMOOTH_RATE", "MATERIAL_SMOOTH_FRACTION", "POLICY_SCHEMA", "POLICY_VERSION",
    "SHELL_SMOOTH_TARGET", "SMOOTH_ROUGHNESS", "choose_for_role", "finish_report",
    "load_policy", "measure_roughness", "roughness_index", "shell_smooth_fraction",
    "smooth_rate_for", "stable_digest",
]
