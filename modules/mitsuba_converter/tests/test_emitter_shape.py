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
