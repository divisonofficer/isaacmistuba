from __future__ import annotations

import xml.etree.ElementTree as ET

import numpy as np

from mitsuba_converter.polar_heading_batch import (
    shared_stokes_reference_axis,
    split_stokes_heading_batch,
    stage_ambient_stokes_heading_batch,
    stage_resident_ambient_stokes_heading_batch,
)


def test_stage_ambient_stokes_heading_batch_preserves_order_and_k1_stokes_basis(tmp_path):
    source = tmp_path / "stokes.xml"
    source.write_text(
        """<scene version=\"3.0.0\">
  <integrator type=\"stokes\"/>
  <sensor type=\"perspective\" id=\"sensor\">
    <float name=\"fov\" value=\"60\"/>
    <film type=\"hdrfilm\"><integer name=\"width\" value=\"16\"/><integer name=\"height\" value=\"8\"/></film>
    <sampler type=\"independent\"><integer name=\"sample_count\" value=\"1\"/></sampler>
  </sensor>
</scene>""",
        encoding="utf-8",
    )
    output = tmp_path / "batch.xml"
    poses = [
        [1, 0, 0, 1, 0, 1, 0, 2, 0, 0, 1, 3, 0, 0, 0, 1],
        [1, 0, 0, 4, 0, 1, 0, 5, 0, 0, 1, 6, 0, 0, 0, 1],
    ]

    assert stage_ambient_stokes_heading_batch(source, output, camera_to_worlds=poses, width=16, height=8, fov_deg=75) == 2

    root = ET.parse(output).getroot()
    axis = root.find("./integrator/vector[@name='reference_axis']")
    assert axis is not None
    assert axis.attrib == {"name": "reference_axis", "x": "0.0", "y": "1.0", "z": "0.0"}
    sensor = root.find("./sensor")
    assert sensor.attrib["type"] == "batch"
    assert sensor.find("./film/integer[@name='width']").attrib["value"] == "32"
    children = sensor.findall("./sensor")
    assert [child.attrib["name"] for child in children] == ["heading_00", "heading_01"]
    assert children[0].find("./transform/lookat").attrib["origin"] == "1.000000000,2.000000000,3.000000000"
    assert children[1].find("./transform/lookat").attrib["origin"] == "4.000000000,5.000000000,6.000000000"


def test_split_stokes_heading_batch_requires_native_shape_and_preserves_strips():
    image = np.arange(2 * 12 * 15, dtype=np.float32).reshape(2, 12, 15)
    strips = split_stokes_heading_batch(image, batch_size=3, width=4, height=2)
    assert len(strips) == 3
    assert strips[0].shape == (2, 4, 15)
    assert np.array_equal(strips[1], image[:, 4:8, :])

    with np.testing.assert_raises_regex(ValueError, "expected Stokes batch film"):
        split_stokes_heading_batch(image, batch_size=4, width=4, height=2)


def test_stage_resident_heading_batch_keeps_immutable_named_slots(tmp_path):
    source = tmp_path / "stokes.xml"
    source.write_text(
        """<scene version="3.0.0">
  <integrator type="stokes"/>
  <sensor type="perspective" id="sensor">
    <float name="fov" value="60"/>
    <film type="hdrfilm"><integer name="width" value="16"/><integer name="height" value="8"/></film>
    <sampler type="independent"><integer name="sample_count" value="1"/></sampler>
  </sensor>
</scene>""",
        encoding="utf-8",
    )
    output = tmp_path / "resident-batch.xml"

    assert stage_resident_ambient_stokes_heading_batch(
        source, output, batch_size=3, width=16, height=8, fov_deg=75,
        stokes_reference_axis=(0.0, 1.0, 0.0),
    ) == 3
    before = output.read_bytes()
    before_mtime_ns = output.stat().st_mtime_ns
    # A second call must preserve the stable file identity used by the
    # process-local Mitsuba resident-scene cache.
    assert stage_resident_ambient_stokes_heading_batch(
        source, output, batch_size=3, width=16, height=8, fov_deg=75,
        stokes_reference_axis=(0.0, 1.0, 0.0),
    ) == 3
    assert output.read_bytes() == before
    assert output.stat().st_mtime_ns == before_mtime_ns

    root = ET.parse(output).getroot()
    sensor = root.find("./sensor")
    assert sensor is not None
    assert sensor.attrib["type"] == "batch"
    assert sensor.find("./film/integer[@name='width']").attrib["value"] == "48"
    assert [child.attrib["name"] for child in sensor.findall("./sensor")] == [
        "heading_00", "heading_01", "heading_02",
    ]


def test_shared_stokes_reference_axis_uses_world_gravity_for_pitched_yaw_sweeps():
    upright = np.eye(4, dtype=np.float64)
    yaw_only = np.eye(4, dtype=np.float64)
    yaw_only[:3, :3] = np.array([
        [0.0, 0.0, 1.0],
        [0.0, 1.0, 0.0],
        [-1.0, 0.0, 0.0],
    ])
    assert shared_stokes_reference_axis([upright, yaw_only]) == (0.0, 1.0, 0.0)

    pitched = np.eye(4, dtype=np.float64)
    pitched[:3, :3] = np.array([
        [1.0, 0.0, 0.0],
        [0.0, 0.984807753, -0.173648178],
        [0.0, 0.173648178, 0.984807753],
    ])
    assert shared_stokes_reference_axis([upright, yaw_only, pitched]) == (0.0, 1.0, 0.0)

    vertical = np.eye(4, dtype=np.float64)
    vertical[:3, :3] = np.array([
        [1.0, 0.0, 0.0],
        [0.0, 0.0, -1.0],
        [0.0, 1.0, 0.0],
    ])
    with np.testing.assert_raises_regex(ValueError, "near vertical"):
        shared_stokes_reference_axis([upright, vertical])
