"""Scene staging contract for batched ambient Stokes headings.

The OptiX7 production renderer pays a substantial graph-recording cost for
each heading.  Mitsuba's ``batch`` sensor lets a worker render several camera
poses into one wide Stokes film, which can then be split into ordinary
``H x W x 15`` frames.  This module deliberately owns only the XML contract;
worker/ledger fan-out is kept separate so a partially completed batch can
never be mistaken for four completed observation bundles.

It is valid only for an ambient/base Stokes scene.  A camera-aligned active
polarizer is pose-dependent and must remain a one-heading scene until it has
its own batch-light implementation.
"""
from __future__ import annotations

import copy
import os
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Iterable, Sequence

import numpy as np


# OpticalNav expresses horizontal navigation in Mitsuba X/Z coordinates, so
# gravity is +Y. A world-fixed Stokes frame is intentional: the camera has a
# small downward pitch and its local image-up rotates as the robot yaws. That
# local frame cannot be represented by the single outer integrator of a batch
# sensor. A common world frame can be, and is also used by K=1 renders.
CANONICAL_STOKES_REFERENCE_AXIS = (0.0, 1.0, 0.0)


def normalize_camera_to_world(matrix: Sequence[float] | np.ndarray) -> np.ndarray:
    """Return column-translation 4x4 storage from either supported input form."""
    result = np.asarray(matrix, dtype=np.float64).reshape(4, 4)
    column_norm = float(np.linalg.norm(result[:3, 3]))
    row_norm = float(np.linalg.norm(result[3, :3]))
    if row_norm > max(1e-5, column_norm * 2.0):
        result = result.T
    if not np.isfinite(result).all():
        raise ValueError("camera_to_world must contain only finite values")
    return result


def _set_sensor_transform(sensor: ET.Element, camera_to_world: np.ndarray) -> None:
    for child in list(sensor):
        if child.tag == "transform" and child.attrib.get("name") == "to_world":
            sensor.remove(child)
    transform = ET.Element("transform", {"name": "to_world"})
    origin = camera_to_world[:3, 3]
    target = origin - camera_to_world[:3, 2]
    up = camera_to_world[:3, 1]
    ET.SubElement(
        transform,
        "lookat",
        {
            "origin": ",".join(f"{float(value):.9f}" for value in origin),
            "target": ",".join(f"{float(value):.9f}" for value in target),
            "up": ",".join(f"{float(value):.9f}" for value in up),
        },
    )
    sensor.insert(0, transform)


def shared_stokes_reference_axis(
    camera_to_worlds: Iterable[Sequence[float] | np.ndarray],
    *,
    alignment_tolerance: float = 1e-5,
) -> tuple[float, float, float]:
    """Return the canonical global Stokes axis for a navigation heading strip.

    A batch sensor has one outer Stokes integrator, so a strip cannot use a
    different sensor-local reference axis for every child camera. OpticalNav
    instead defines S1/S2/AoLP in the gravity-aligned Mitsuba world frame.
    This remains invariant under yaw and matches the explicit K=1 policy. We
    only reject cameras looking essentially straight along gravity, where the
    projection of that reference frame onto the image plane is undefined.
    """
    poses = [normalize_camera_to_world(pose) for pose in camera_to_worlds]
    if not poses:
        raise ValueError("a Stokes heading batch needs at least one camera pose")
    reference = np.asarray(CANONICAL_STOKES_REFERENCE_AXIS, dtype=np.float64)
    for index, pose in enumerate(poses):
        forward = -np.asarray(pose[:3, 2], dtype=np.float64)
        norm = float(np.linalg.norm(forward))
        if not np.isfinite(norm) or norm <= 1e-9:
            raise ValueError(f"Stokes heading batch pose {index} has a degenerate camera forward axis")
        # ``cross(ray.d, reference_axis)`` is the target Stokes basis. It
        # degenerates when camera forward is parallel to gravity. Keep the
        # tolerance explicit even though navigation cameras are horizontal.
        if abs(float(np.dot(forward / norm, reference))) > 1.0 - float(alignment_tolerance):
            raise ValueError(
                "Stokes heading batch camera is near vertical relative to the "
                f"canonical world reference axis (pose {index} must render with a non-degenerate frame)"
            )
    return CANONICAL_STOKES_REFERENCE_AXIS


def _normalized_reference_axis(axis: Sequence[float] | np.ndarray) -> tuple[float, float, float]:
    result = np.asarray(axis, dtype=np.float64).reshape(-1)
    if result.shape != (3,) or not np.isfinite(result).all():
        raise ValueError("stokes_reference_axis must be a finite 3-vector")
    norm = float(np.linalg.norm(result))
    if norm <= 1e-9:
        raise ValueError("stokes_reference_axis must be non-zero")
    result /= norm
    return tuple(float(value) for value in result)


def _set_stokes_reference_axis(integrator: ET.Element, axis: Sequence[float] | np.ndarray) -> None:
    for child in list(integrator):
        if child.tag == "vector" and child.attrib.get("name") == "reference_axis":
            integrator.remove(child)
    x, y, z = _normalized_reference_axis(axis)
    # The OptiX7 Stokes plugin uses this world-space vector to align every
    # child strip to its K=1 camera-up basis.  It must be explicit: the batch
    # parent transform cannot identify the active child camera.
    integrator.insert(0, ET.Element(
        "vector", {"name": "reference_axis", "x": str(x), "y": str(y), "z": str(z)}
    ))


def stage_ambient_stokes_heading_batch(
    source_scene: str | Path,
    output_scene: str | Path,
    *,
    camera_to_worlds: Iterable[Sequence[float] | np.ndarray],
    width: int,
    height: int,
    fov_deg: float,
    stokes_reference_axis: Sequence[float] | np.ndarray | None = None,
) -> int:
    """Stage a K-heading Stokes batch scene and atomically publish its XML.

    The output film is ordered left-to-right in the same order as
    ``camera_to_worlds``.  The outer Stokes integrator receives the shared
    world-space camera-up axis, which makes its S1/S2 basis match ordinary K=1
    renders for an upright yaw-only rig.  A batch whose child cameras have
    different up axes is rejected rather than silently producing a mixed
    basis.
    """
    poses = [normalize_camera_to_world(pose) for pose in camera_to_worlds]
    if len(poses) < 2:
        raise ValueError("a heading batch needs at least two camera poses")
    if width <= 0 or height <= 0:
        raise ValueError("batch film width and height must be positive")
    source = Path(source_scene)
    output = Path(output_scene)
    root = ET.parse(source).getroot()
    integrator = root.find("./integrator")
    sensor = root.find("./sensor")
    if integrator is None or integrator.attrib.get("type") != "stokes":
        raise ValueError("source scene must contain a top-level stokes integrator")
    if sensor is None:
        raise ValueError("source scene has no sensor")
    reference_axis = (
        _normalized_reference_axis(stokes_reference_axis)
        if stokes_reference_axis is not None
        else shared_stokes_reference_axis(poses)
    )
    _set_stokes_reference_axis(integrator, reference_axis)

    child_template = copy.deepcopy(sensor)
    child_template.attrib.pop("id", None)
    for child in list(child_template):
        if child.tag in {"film", "sampler"}:
            child_template.remove(child)

    sensor.attrib["type"] = "batch"
    for child in list(sensor):
        if child.tag == "transform" and child.attrib.get("name") == "to_world":
            sensor.remove(child)
        if child.tag == "float" and child.attrib.get("name") == "fov":
            sensor.remove(child)
    for index, pose in enumerate(poses):
        child = copy.deepcopy(child_template)
        child.attrib["name"] = f"heading_{index:02d}"
        _set_sensor_transform(child, pose)
        fov = child.find("./float[@name='fov']")
        if fov is None:
            fov = ET.SubElement(child, "float", {"name": "fov"})
        fov.attrib["value"] = f"{float(fov_deg):.9f}"
        sensor.append(child)

    film = sensor.find("./film")
    if film is None:
        raise ValueError("source sensor has no film")
    for name, value in (("width", int(width) * len(poses)), ("height", int(height))):
        element = film.find(f"./integer[@name='{name}']")
        if element is None:
            element = ET.SubElement(film, "integer", {"name": name})
        element.attrib["value"] = str(value)

    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.{os.getpid()}.tmp")
    ET.ElementTree(root).write(temporary, encoding="utf-8", xml_declaration=True)
    temporary.replace(output)
    return len(poses)


def stage_resident_ambient_stokes_heading_batch(
    source_scene: str | Path,
    output_scene: str | Path,
    *,
    batch_size: int,
    width: int,
    height: int,
    fov_deg: float,
    stokes_reference_axis: Sequence[float] | np.ndarray,
) -> int:
    """Publish an immutable K-slot Stokes batch scene for resident reuse.

    The scene starts with identity sensor transforms.  A persistent worker
    updates the named ``heading_XX.to_world`` parameters through
    ``mi.traverse`` before each render, so its geometry, textures and OptiX
    acceleration structures remain resident.  The output must be immutable:
    rewriting it would change its cache key and force a new ``mi.load_file``.
    """
    slots = int(batch_size)
    if slots < 2 or slots > 4:
        raise ValueError("resident Stokes heading batches require 2 to 4 slots")
    if width <= 0 or height <= 0:
        raise ValueError("batch film width and height must be positive")
    output = Path(output_scene)
    if output.exists():
        return slots
    # Build a complete, unique sibling first.  ``link`` then atomically claims
    # the immutable canonical name only if no other worker has won the race.
    # Unlike ``replace``, a losing process never changes the canonical XML's
    # mtime and therefore cannot invalidate another worker's resident cache.
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    count = stage_ambient_stokes_heading_batch(
        source_scene,
        temporary,
        camera_to_worlds=[np.eye(4, dtype=np.float64) for _ in range(slots)],
        width=width,
        height=height,
        fov_deg=fov_deg,
        stokes_reference_axis=stokes_reference_axis,
    )
    try:
        os.link(temporary, output)
    except FileExistsError:
        # Another worker published the same signature first.  Its XML is
        # byte-equivalent, and its stable mtime is now the cache identity.
        pass
    finally:
        temporary.unlink(missing_ok=True)
    return count


def split_stokes_heading_batch(image: np.ndarray, *, batch_size: int, width: int, height: int) -> list[np.ndarray]:
    """Split a Mitsuba batch film into ordinary per-heading Stokes tensors.

    ``stokes`` renders must have the native 15 channels (unpolarized RGB plus
    four RGB Stokes components).  Refusing other shapes here makes a bad
    batch scene fail before any observation manifest can be committed.
    """
    array = np.asarray(image, dtype=np.float32)
    expected = (int(height), int(width) * int(batch_size), 15)
    if array.shape != expected:
        raise ValueError(f"expected Stokes batch film {expected}, got {tuple(array.shape)}")
    if not np.isfinite(array).all():
        raise ValueError("Stokes batch film contains non-finite values")
    return [np.ascontiguousarray(strip) for strip in np.split(array, int(batch_size), axis=1)]
