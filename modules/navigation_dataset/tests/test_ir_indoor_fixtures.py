from __future__ import annotations

import pytest

from navigation_dataset.ir_indoor_fixtures import (
    FIXTURE_GROUPS,
    SWITCHABLE_GROUPS,
    blackbody_linear_rgb,
    classify_fixture,
    fixture_id,
    luminance,
    rig_digest,
)


def test_a_ceiling_lamp_is_classified_by_height_not_by_lamp_type() -> None:
    """The rule this replaces kept only AREA lamps, which deleted real fixtures.

    Measured on a prepared bathroom: five generator-placed lights, all disabled,
    including two POINT lamps at 2.66 m that are plainly ceiling lights. Height
    inside a traversable room is what makes a ceiling fixture, not its datablock
    type.
    """
    for blender_type in ("POINT", "AREA", "SPOT"):
        assert classify_fixture(
            blender_type=blender_type, position_z_m=2.66, in_traversable_room=True,
        ) == "ceiling", blender_type


def test_groups_split_by_height_and_room_membership() -> None:
    assert classify_fixture(blender_type="POINT", position_z_m=1.05, in_traversable_room=True) == "lamp"
    assert classify_fixture(blender_type="POINT", position_z_m=0.10, in_traversable_room=True) == "accent"
    # A tight spot is an accent wherever it hangs.
    assert classify_fixture(blender_type="SPOT", position_z_m=2.4, in_traversable_room=True,
                            spot_size_deg=30.0) == "accent"
    # A wide spot at ceiling height is just a ceiling light.
    assert classify_fixture(blender_type="SPOT", position_z_m=2.4, in_traversable_room=True,
                            spot_size_deg=90.0) == "ceiling"


def test_a_light_outside_every_room_keeps_the_legacy_disable() -> None:
    """That case is the uncontrolled variance the original policy removed."""
    assert classify_fixture(blender_type="POINT", position_z_m=2.6,
                            in_traversable_room=False) == "exterior"
    assert "exterior" not in SWITCHABLE_GROUPS


def test_portals_are_not_switchable() -> None:
    """The worker rewrites portal energy from the HDRI recipe after fixtures.

    A portal mask would therefore be silently overwritten, so portals must never
    reach the switchable set.
    """
    assert classify_fixture(blender_type="AREA", position_z_m=1.2, in_traversable_room=True,
                            is_external_portal=True) == "portal"
    assert "portal" not in SWITCHABLE_GROUPS
    assert set(SWITCHABLE_GROUPS) <= set(FIXTURE_GROUPS)


def test_synthetic_rigs_keep_their_own_group() -> None:
    assert classify_fixture(blender_type="AREA", position_z_m=2.5, in_traversable_room=True,
                            is_ambient_fill=True) == "ambient_fill"


def test_fixture_id_is_stable_and_distinct() -> None:
    a = fixture_id(group="ceiling", room_id="room_00", object_name="PointLamp.001")
    assert a == fixture_id(group="ceiling", room_id="room_00", object_name="PointLamp.001")
    assert a != fixture_id(group="ceiling", room_id="room_00", object_name="PointLamp.002")
    assert a.startswith("ceiling:room_00:")


def test_blackbody_is_monotone_and_normalised() -> None:
    previous = None
    for kelvin in (2000, 2700, 3000, 4000, 5000, 6500):
        rgb = blackbody_linear_rgb(kelvin)
        assert max(rgb) == pytest.approx(1.0, abs=1e-6), kelvin
        assert all(0.0 <= c <= 1.0 for c in rgb), kelvin
        # Warmer light is redder: blue rises with temperature.
        if previous is not None:
            assert rgb[2] > previous, kelvin
        previous = rgb[2]
    assert blackbody_linear_rgb(20000)[2] == pytest.approx(1.0, abs=1e-6)


def test_a_warm_tint_costs_real_luminance_in_the_nir_band() -> None:
    """Colour is an RGB-only variation, but not a free one.

    The worker collapses every light colour to Rec.709 luminance for the NIR
    band. Under max-channel normalisation a 2700 K fixture keeps only about half
    the luminance of a neutral one, so a nominally colour-only condition is
    substantially dimmer in NIR. Any ablation that treats tint as NIR-invariant
    has to compensate for this, and the number belongs in the record.
    """
    warm = luminance(blackbody_linear_rgb(2700))
    cool = luminance(blackbody_linear_rgb(6500))
    assert warm < 0.60, warm
    assert cool > 0.90, cool
    assert cool / warm > 1.7


def test_rig_digest_ignores_ordering() -> None:
    rows = [
        {"fixture_id": "ceiling:r0:aaaa", "group": "ceiling", "room_id": "r0", "base_energy_w": 47.07},
        {"fixture_id": "lamp:r0:bbbb", "group": "lamp", "room_id": "r0", "base_energy_w": 90.84},
    ]
    assert rig_digest(rows) == rig_digest(list(reversed(rows)))
    assert rig_digest(rows) != rig_digest(rows[:1])
