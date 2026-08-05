from __future__ import annotations

import xml.etree.ElementTree as ET

from mitsuba_converter.render_daemon import _proxy_box_xml_element


def _emitter(**over):
    obj = {
        "id": "lp",
        "label": "light:test",
        "is_emitter": True,
        "emitter_radiance": [3.0, 3.0, 3.0],
        "emitter_intensity": 1.0,
        "material": "m",
        "geometry": {"type": "point", "center": [1.0, 2.0], "size_m": [0.6, 0.08, 0.6],
                     "base_height_m": 2.55, "yaw_deg": 0.0},
    }
    obj.update(over)
    return _proxy_box_xml_element(obj, {}, {})


def test_ceiling_panel_emits_downward_rectangle() -> None:
    el = _emitter(emitter_shape="ceiling_panel")
    assert el.get("type") == "rectangle"
    xf = el.find("./transform")
    rot = xf.find("./rotate")
    assert rot is not None and rot.get("x") == "1" and rot.get("angle") == "90"  # +Z normal -> -Y (down)
    scale = xf.find("./scale")
    assert float(scale.get("x")) == 0.3 and float(scale.get("y")) == 0.3  # sx/2, sz/2
    em = el.find("./emitter")
    assert em is not None and em.get("type") == "area"
    assert el.find("./transform/translate").get("y") == "2.590000"  # below the 2.6 ceiling


def test_non_ceiling_emitter_stays_cube() -> None:
    el = _emitter()  # no emitter_shape flag
    assert el.get("type") == "cube"
    assert el.find("./emitter").get("type") == "area"


def test_rgb_directional_wall_panel_has_four_emitters_and_polarizer() -> None:
    elements = _emitter(
        emitter_shape="wall_panel",
        emitter_pattern="rgb_directional",
        emitter_polarized=True,
        emitter_polarizer_angle_deg=17.5,
        geometry={
            "type": "point",
            "center": [1.0, 2.0],
            "size_m": [2.4, 1.35, 0.03],
            "base_height_m": 0.6,
            "yaw_deg": 90.0,
        },
    )
    assert isinstance(elements, list) and len(elements) == 5
    emitters = [el for el in elements if el.find("./emitter") is not None]
    assert len(emitters) == 4
    radiances = {
        el.get("id"): el.find("./emitter/rgb[@name='radiance']").get("value")
        for el in emitters
    }
    assert radiances["lp_upper_left"] == "0 3 3"
    assert radiances["lp_upper_right"] == "3 0 3"
    assert radiances["lp_lower_left"] == "0 3 0"
    assert radiances["lp_lower_right"] == "3 0 0"
    polarizer = next(el for el in elements if el.get("id") == "lp_polarizer")
    theta = polarizer.find("./bsdf[@type='polarizer']/float[@name='theta']")
    assert theta is not None and theta.get("value") == "17.5000"
