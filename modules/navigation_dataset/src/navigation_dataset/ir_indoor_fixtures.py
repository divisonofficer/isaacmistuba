"""Addressable indoor light fixtures for the IR dataset.

Stage-2 preparation currently keeps a light only when it is an ``AREA`` lamp
inside a traversable room above 1.5 m, and disables everything else as a
variance source.  Measured on a prepared bathroom that removes every fixture the
generator placed -- five lights, of which two are genuine ceiling lamps at
2.66 m killed only for being ``POINT`` rather than ``AREA`` -- leaving the room
lit by a single 30 W synthetic softbox.  Indoor lighting variation then has
nowhere to come from except that one panel's brightness and tint.

This module gives every light a stable identity and a group, so a lighting
condition can switch and tint fixtures individually instead of scaling all of
them at once.  It is renderer-independent and importable from the repository
bundled Blender Python: the Blender side supplies plain values, and gets back a
classification it can write onto the light datablock.
"""
from __future__ import annotations

import hashlib
import math
from typing import Any, Mapping, Sequence

FIXTURE_RIG_SCHEMA = "robomituba.ir_indoor_fixture_rig.v1"
CLASSIFIER_VERSION = "fixture-group-geometric-v1"
COLOR_TEMPERATURE_MODEL = "planckian_cie1931_rec709_maxnorm_v1"

#: ``exterior`` keeps the legacy disable: a light outside every traversable room
#: is the uncontrolled variance the original policy was written to remove.
FIXTURE_GROUPS = ("ceiling", "lamp", "accent", "ambient_fill", "portal", "exterior")
#: Groups a lighting condition may switch.  ``portal`` is excluded on purpose --
#: the worker rewrites portal energy from the HDRI recipe *after* fixture
#: application, so a mask here would be silently overwritten.
SWITCHABLE_GROUPS = ("ceiling", "lamp", "accent", "ambient_fill")

CEILING_MIN_HEIGHT_M = 1.5
LAMP_MIN_HEIGHT_M = 0.3
ACCENT_SPOT_MAX_ANGLE_DEG = 45.0


def classify_fixture(
    *, blender_type: str, position_z_m: float, in_traversable_room: bool,
    is_ambient_fill: bool = False, is_external_portal: bool = False,
    spot_size_deg: float | None = None,
) -> str:
    """Return the switching group for one light.

    Geometric, not name-based: the two markers the prepare stage already writes
    identify the synthetic rigs, and everything else is placed by height inside
    the room.  Note this deliberately drops the ``AREA``-only requirement --
    a ``POINT`` lamp at ceiling height is a ceiling light, and treating it as
    one is the whole point of the change.
    """
    if is_ambient_fill:
        return "ambient_fill"
    if is_external_portal:
        return "portal"
    if not in_traversable_room:
        return "exterior"
    if str(blender_type).upper() == "SPOT" and spot_size_deg is not None \
            and float(spot_size_deg) < ACCENT_SPOT_MAX_ANGLE_DEG:
        return "accent"
    height = float(position_z_m)
    if height > CEILING_MIN_HEIGHT_M:
        return "ceiling"
    if height >= LAMP_MIN_HEIGHT_M:
        return "lamp"
    return "accent"


def fixture_id(*, group: str, room_id: str, object_name: str) -> str:
    """A stable id that survives renaming rooms but not renaming the light."""
    digest = hashlib.sha256(str(object_name).encode("utf-8")).hexdigest()[:8]
    return f"{group}:{room_id or 'none'}:{digest}"


def _planckian_xy(kelvin: float) -> tuple[float, float]:
    """CIE 1931 xy on the Planckian locus (Kim et al. approximation)."""
    t = min(max(float(kelvin), 1667.0), 25000.0)
    if t <= 4000.0:
        x = (-0.2661239e9 / t ** 3) - (0.2343589e6 / t ** 2) + (0.8776956e3 / t) + 0.179910
    else:
        x = (-3.0258469e9 / t ** 3) + (2.1070379e6 / t ** 2) + (0.2226347e3 / t) + 0.240390
    if t <= 2222.0:
        y = -1.1063814 * x ** 3 - 1.34811020 * x ** 2 + 2.18555832 * x - 0.20219683
    elif t <= 4000.0:
        y = -0.9549476 * x ** 3 - 1.37418593 * x ** 2 + 2.09137015 * x - 0.16748867
    else:
        y = 3.0817580 * x ** 3 - 5.87338670 * x ** 2 + 3.75112997 * x - 0.37001483
    return x, y


def blackbody_linear_rgb(kelvin: float) -> tuple[float, float, float]:
    """Linear Rec.709 for a colour temperature, normalised to a max of 1.

    Max-normalised rather than luminance-normalised so a condition's
    ``energy_scale`` remains the only control over brightness.  The NIR band
    collapses colour to luminance, so a tint is an RGB-only variation there --
    recorded explicitly by the caller rather than left implicit.
    """
    x, y = _planckian_xy(kelvin)
    if y <= 1e-6:
        return (1.0, 1.0, 1.0)
    big_x, big_y, big_z = x / y, 1.0, (1.0 - x - y) / y
    r = 3.2404542 * big_x - 1.5371385 * big_y - 0.4985314 * big_z
    g = -0.9692660 * big_x + 1.8760108 * big_y + 0.0415560 * big_z
    b = 0.0556434 * big_x - 0.2040259 * big_y + 1.0572252 * big_z
    rgb = [max(0.0, value) for value in (r, g, b)]
    peak = max(rgb)
    if peak <= 1e-9:
        return (1.0, 1.0, 1.0)
    return tuple(round(value / peak, 6) for value in rgb)  # type: ignore[return-value]


def luminance(rgb: Sequence[float]) -> float:
    """Rec.709 luminance, the value the NIR band collapses a light colour to."""
    weights = (0.2126, 0.7152, 0.0722)
    return float(sum(float(rgb[i]) * weights[i] for i in range(3)))


def rig_digest(fixtures: Sequence[Mapping[str, Any]]) -> str:
    """Identity of the fixture inventory, independent of listing order."""
    import json
    rows = sorted(
        (
            {
                "fixture_id": str(row.get("fixture_id")),
                "group": str(row.get("group")),
                "room_id": str(row.get("room_id") or ""),
                "base_energy_w": round(float(row.get("base_energy_w") or 0.0), 6),
            }
            for row in fixtures
        ),
        key=lambda row: row["fixture_id"],
    )
    return hashlib.sha256(
        json.dumps(rows, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


__all__ = [
    "ACCENT_SPOT_MAX_ANGLE_DEG",
    "CEILING_MIN_HEIGHT_M",
    "CLASSIFIER_VERSION",
    "COLOR_TEMPERATURE_MODEL",
    "FIXTURE_GROUPS",
    "FIXTURE_RIG_SCHEMA",
    "LAMP_MIN_HEIGHT_M",
    "SWITCHABLE_GROUPS",
    "blackbody_linear_rgb",
    "classify_fixture",
    "fixture_id",
    "luminance",
    "rig_digest",
]
