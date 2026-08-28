from __future__ import annotations

import xml.etree.ElementTree as ET

import numpy as np
import pytest

from mitsuba_converter.multimodal import (
    RenderConfig,
    _polar_transport_integrator,
    _stage_stokes_scene,
)
from mitsuba_converter.observation_bridge import render_config_from_payload


def test_physical_transport_is_the_default_path_integrator() -> None:
    config = RenderConfig(path_max_depth=7)

    assert config.polar_transport == "physical"
    assert _polar_transport_integrator(config) == ("path", 7)


def test_preview_transport_keeps_direct_integrator() -> None:
    config = RenderConfig(polar_transport="preview", direct_max_depth=3)

    assert _polar_transport_integrator(config) == ("direct", 3)


def test_saved_request_without_transport_uses_physical_default() -> None:
    config = render_config_from_payload({"polar_spp": 16})

    assert config.polar_transport == "physical"


def test_unknown_polar_transport_is_rejected() -> None:
    with pytest.raises(ValueError, match="polar_transport"):
        render_config_from_payload({"polar_transport": "volpath"})


def test_physical_stokes_stage_uses_path_and_path_depth(tmp_path) -> None:
    """The public mode must survive scene staging, not only config resolution."""
    source = tmp_path / "source.xml"
    source.write_text(
        "<scene version='3.0.0'><integrator type='direct'/>"
        "<sensor type='perspective'><sampler type='independent'/>"
        "<film type='hdrfilm'/></sensor></scene>",
        encoding="utf-8",
    )
    staged = _stage_stokes_scene(
        source, tmp_path / "physical_stokes.xml",
        camera_to_world=np.eye(4), fov_deg=65.0, spp=4, width=16, height=12,
        samples_per_pass=None, nested_integrator_type="path", nested_max_depth=9,
    )

    root = ET.parse(staged).getroot()
    outer = root.find("./integrator")
    assert outer is not None and outer.attrib["type"] == "stokes"
    nested = outer.find("./integrator")
    assert nested is not None and nested.attrib["type"] == "path"
    assert nested.find("./integer[@name='max_depth']").attrib["value"] == "9"
