"""Canonical OpticalNav camera poses and Blender axis adapters.

The navigation graph stores positions in the authoring ``XZ`` floor frame:
``[x, authoring_y, 0]``.  Mitsuba consumes that frame as a Y-up world while
the source Infinigen ``.blend`` remains Blender Z-up.  Keeping the conversion
here prevents each renderer from silently interpreting the graph differently.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Sequence


AXIS_TRANSFORM_ID = "mitsuba_y_up_to_blender_z_up_v1"
MATRIX_LAYOUT = "row_major_4x4"
TRANSLATION_LAYOUT = "row_major_translation_last_column"
LEGACY_FLAT_LAYOUT = "column_major_flat_translation_last"


Vec3 = tuple[float, float, float]
Mat4 = tuple[tuple[float, float, float, float], ...]


def _normalize(v: Vec3) -> Vec3:
    n = math.sqrt(sum(float(x) * float(x) for x in v))
    if n < 1e-12:
        raise ValueError("camera basis contains a near-zero vector")
    return tuple(float(x) / n for x in v)  # type: ignore[return-value]


def _cross(a: Vec3, b: Vec3) -> Vec3:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _sub(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _add(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _mat4_from_columns(right: Vec3, up: Vec3, minus_forward: Vec3, origin: Vec3) -> Mat4:
    return (
        (right[0], up[0], minus_forward[0], origin[0]),
        (right[1], up[1], minus_forward[1], origin[1]),
        (right[2], up[2], minus_forward[2], origin[2]),
        (0.0, 0.0, 0.0, 1.0),
    )


def _mat3_mul_vec(matrix: tuple[tuple[float, float, float], ...], value: Vec3) -> Vec3:
    return tuple(
        sum(float(matrix[row][col]) * float(value[col]) for col in range(3))
        for row in range(3)
    )  # type: ignore[return-value]


def _mat4_mul(a: Mat4, b: Mat4) -> Mat4:
    return tuple(
        tuple(sum(float(a[row][k]) * float(b[k][col]) for k in range(4)) for col in range(4))
        for row in range(4)
    )  # type: ignore[return-value]


def _origin_offset3(origin_offset: Sequence[float] | None) -> Vec3:
    """Return the Infinigen authoring normalization offset as ``[dx, dy, dz]``."""
    if origin_offset is None:
        return (0.0, 0.0, 0.0)
    if len(origin_offset) < 2 or len(origin_offset) > 3:
        raise ValueError("origin_offset must contain [dx, dy] or [dx, dy, dz]")
    values = [float(v) for v in origin_offset]
    if not all(math.isfinite(v) for v in values):
        raise ValueError("origin_offset values must be finite")
    return (values[0], values[1], values[2] if len(values) == 3 else 0.0)


def _blender_registration_translation(origin_offset: Sequence[float] | None) -> Vec3:
    """Map normalized Mitsuba coordinates back into native Blender world."""
    dx, dy, dz = _origin_offset3(origin_offset)
    # graph/Mitsuba normalizes (x, z, y-up) by (+dx, +dy, +dz);
    # inverse registration after the Y-up -> Z-up rotation is (-dx, +dy, -dz).
    return (-dx, dy, -dz)


def _with_translation(matrix: Mat4, translation: Vec3) -> Mat4:
    rows = [list(row) for row in matrix]
    for row in range(3):
        rows[row][3] += float(translation[row])
    return tuple(tuple(row) for row in rows)  # type: ignore[return-value]


_MITSUBA_TO_BLENDER_3 = (
    (1.0, 0.0, 0.0),
    (0.0, 0.0, -1.0),
    (0.0, 1.0, 0.0),
)
_MITSUBA_TO_BLENDER_4: Mat4 = (
    (1.0, 0.0, 0.0, 0.0),
    (0.0, 0.0, -1.0, 0.0),
    (0.0, 1.0, 0.0, 0.0),
    (0.0, 0.0, 0.0, 1.0),
)


@dataclass(frozen=True)
class CanonicalCameraPose:
    """Resolved graph camera in both canonical Mitsuba and Blender frames."""

    origin_mitsuba: Vec3
    target_mitsuba: Vec3
    up_mitsuba: Vec3
    camera_to_world_mitsuba: Mat4
    origin_blender: Vec3
    target_blender: Vec3
    up_blender: Vec3
    camera_to_world_blender: Mat4
    yaw_deg: float
    eye_height_m: float
    target_height_m: float
    authoring_origin_offset: Vec3 = (0.0, 0.0, 0.0)
    pose_source: str = "canonical_graph"
    fov_axis: str = "x"
    axis_transform: str = AXIS_TRANSFORM_ID

    def provenance(self) -> dict[str, object]:
        return {
            "pose_source": self.pose_source,
            "coordinate_system": "blender_z_up",
            "camera_coordinate_system": "mitsuba_y_up",
            "camera_to_world_mitsuba": [list(row) for row in self.camera_to_world_mitsuba],
            "camera_to_world_blender": [list(row) for row in self.camera_to_world_blender],
            "origin_mitsuba": list(self.origin_mitsuba),
            "target_mitsuba": list(self.target_mitsuba),
            "up_mitsuba": list(self.up_mitsuba),
            "origin_blender": list(self.origin_blender),
            "target_blender": list(self.target_blender),
            "up_blender": list(self.up_blender),
            "axis_transform": self.axis_transform,
            "authoring_origin_offset": list(self.authoring_origin_offset),
            "blender_world_registration": list(
                _blender_registration_translation(self.authoring_origin_offset)
            ),
            "matrix_layout": MATRIX_LAYOUT,
            "translation_layout": TRANSLATION_LAYOUT,
            "legacy_flat_layout": LEGACY_FLAT_LAYOUT,
            "fov_axis": self.fov_axis,
            "yaw_deg": self.yaw_deg,
            "eye_height_m": self.eye_height_m,
            "target_height_m": self.target_height_m,
        }


def resolve_viewpoint_pose(
    position: Sequence[float],
    yaw_deg: float,
    *,
    eye_height_m: float = 1.2,
    target_height_m: float | None = None,
    origin_offset: Sequence[float] | None = None,
) -> CanonicalCameraPose:
    """Resolve ``[authoring_x, authoring_y, ...]`` into a canonical camera.

    The graph's second coordinate is authoring-world Z in the floor plan, not
    Blender's vertical Y.  In Mitsuba it becomes the world Z coordinate while
    the eye height becomes world Y.  The target-height default intentionally
    preserves the existing kitchen/Mitsuba contract (0.9 of eye height).
    """
    if len(position) < 2:
        raise ValueError("viewpoint position must contain [x, authoring_y]")
    x = float(position[0])
    authoring_y = float(position[1])
    eye = float(eye_height_m)
    if not math.isfinite(x) or not math.isfinite(authoring_y) or not math.isfinite(eye):
        raise ValueError("viewpoint pose values must be finite")
    if eye <= 0.0:
        raise ValueError("eye_height_m must be positive")
    target_height = eye * 0.9 if target_height_m is None else float(target_height_m)
    if not math.isfinite(target_height):
        raise ValueError("target_height_m must be finite")

    yaw = math.radians(float(yaw_deg))
    horizontal_forward = _normalize((math.sin(yaw), 0.0, math.cos(yaw)))
    origin_m = (x, eye, authoring_y)
    target_m = (
        x + horizontal_forward[0],
        target_height,
        authoring_y + horizontal_forward[2],
    )
    # The target height is part of the camera contract, not provenance-only
    # metadata.  Build the basis from the complete look-at vector so every
    # consumer observes the same pitch.
    forward = _normalize(_sub(target_m, origin_m))
    up = (0.0, 1.0, 0.0)
    # This is the bridge's camera-to-world convention: local -Z is forward.
    # ``forward × up`` gives the right-handed camera +X/image-right axis,
    # matching Mitsuba's camera_to_world_from_lookat helper.
    right = _normalize(_cross(forward, up))
    true_up = _normalize(_cross(right, forward))
    mitsuba_matrix = _mat4_from_columns(right, true_up, tuple(-v for v in forward), origin_m)  # type: ignore[arg-type]

    offset = _origin_offset3(origin_offset)
    registration = _blender_registration_translation(offset)
    origin_b_raw = _mat3_mul_vec(_MITSUBA_TO_BLENDER_3, origin_m)
    target_b_raw = _mat3_mul_vec(_MITSUBA_TO_BLENDER_3, target_m)
    origin_b = tuple(origin_b_raw[i] + registration[i] for i in range(3))
    target_b = tuple(target_b_raw[i] + registration[i] for i in range(3))
    up_b = _normalize(_mat3_mul_vec(_MITSUBA_TO_BLENDER_3, up))
    blender_matrix = _with_translation(
        _mat4_mul(_MITSUBA_TO_BLENDER_4, mitsuba_matrix), registration
    )
    return CanonicalCameraPose(
        origin_mitsuba=origin_m,
        target_mitsuba=target_m,
        up_mitsuba=up,
        camera_to_world_mitsuba=mitsuba_matrix,
        origin_blender=origin_b,
        target_blender=target_b,
        up_blender=up_b,
        camera_to_world_blender=blender_matrix,
        yaw_deg=float(yaw_deg),
        eye_height_m=eye,
        target_height_m=target_height,
        authoring_origin_offset=offset,
    )


def pose_from_mitsuba_camera_to_world(
    matrix: Sequence[Sequence[float]] | Sequence[float],
    *,
    pose_source: str = "observation_manifest",
    target_mitsuba: Sequence[float] | None = None,
    origin_offset: Sequence[float] | None = None,
) -> CanonicalCameraPose:
    """Materialize an already-resolved Mitsuba camera pose.

    Observation manifests sometimes carry the final camera matrix rather than
    the graph node/yaw that produced it.  Consumers can use that matrix as the
    authority and still receive the same Blender axis conversion and provenance
    fields as graph-resolved poses.  A flat 16-value matrix uses the bridge's
    legacy column-major/translation-last convention.
    """
    values = list(matrix)
    if len(values) == 16 and (not values or not isinstance(values[0], (list, tuple))):
        rows = legacy_flat_to_matrix(values)
    else:
        rows = tuple(tuple(float(v) for v in row) for row in values)
        if len(rows) != 4 or any(len(row) != 4 for row in rows):
            raise ValueError("camera matrix must be a 4x4 matrix or 16-value flat matrix")
    if not all(math.isfinite(value) for row in rows for value in row):
        raise ValueError("camera matrix must contain only finite values")
    if any(abs(float(rows[3][i]) - expected) > 1e-6 for i, expected in enumerate((0.0, 0.0, 0.0, 1.0))):
        raise ValueError("camera matrix must have homogeneous last row [0, 0, 0, 1]")
    basis = [tuple(float(rows[row][column]) for row in range(3)) for column in range(3)]
    for column in basis:
        length = math.sqrt(sum(value * value for value in column))
        if abs(length - 1.0) > 1e-4:
            raise ValueError("camera matrix rotation columns must be unit length")
    for left, right in ((basis[0], basis[1]), (basis[0], basis[2]), (basis[1], basis[2])):
        if abs(sum(left[i] * right[i] for i in range(3))) > 1e-4:
            raise ValueError("camera matrix rotation columns must be orthogonal")
    origin = (float(rows[0][3]), float(rows[1][3]), float(rows[2][3]))
    forward = _normalize((-float(rows[0][2]), -float(rows[1][2]), -float(rows[2][2])))
    up = _normalize((float(rows[0][1]), float(rows[1][1]), float(rows[2][1])))
    target = tuple(float(v) for v in target_mitsuba) if target_mitsuba is not None else tuple(origin[i] + forward[i] for i in range(3))
    if len(target) != 3:
        raise ValueError("target_mitsuba must contain three coordinates")
    yaw = math.degrees(math.atan2(forward[0], forward[2]))
    offset = _origin_offset3(origin_offset)
    registration = _blender_registration_translation(offset)
    origin_b_raw = _mat3_mul_vec(_MITSUBA_TO_BLENDER_3, origin)
    target_b_raw = _mat3_mul_vec(_MITSUBA_TO_BLENDER_3, target)
    origin_b = tuple(origin_b_raw[i] + registration[i] for i in range(3))
    target_b = tuple(target_b_raw[i] + registration[i] for i in range(3))
    up_b = _normalize(_mat3_mul_vec(_MITSUBA_TO_BLENDER_3, up))
    return CanonicalCameraPose(
        origin_mitsuba=origin,
        target_mitsuba=target,
        up_mitsuba=up,
        camera_to_world_mitsuba=rows,  # type: ignore[arg-type]
        origin_blender=origin_b,
        target_blender=target_b,
        up_blender=up_b,
        camera_to_world_blender=_with_translation(  # type: ignore[arg-type]
            _mat4_mul(_MITSUBA_TO_BLENDER_4, rows), registration
        ),
        yaw_deg=yaw,
        eye_height_m=origin[1],
        target_height_m=target[1],
        authoring_origin_offset=offset,
        pose_source=str(pose_source),
    )


def mitsuba_point_to_blender(
    point: Sequence[float], *, origin_offset: Sequence[float] | None = None
) -> Vec3:
    """Convert a normalized Mitsuba point into native Blender world coordinates."""
    if len(point) < 3:
        raise ValueError("point must contain three coordinates")
    converted = _mat3_mul_vec(
        _MITSUBA_TO_BLENDER_3, (float(point[0]), float(point[1]), float(point[2]))
    )
    registration = _blender_registration_translation(origin_offset)
    return tuple(converted[i] + registration[i] for i in range(3))  # type: ignore[return-value]


def mitsuba_camera_to_blender(
    matrix: Sequence[Sequence[float]], *, origin_offset: Sequence[float] | None = None
) -> Mat4:
    """Apply axis conversion and inverse authoring normalization to a camera matrix."""
    rows = tuple(tuple(float(v) for v in row) for row in matrix)
    if len(rows) != 4 or any(len(row) != 4 for row in rows):
        raise ValueError("camera matrix must be 4x4")
    return _with_translation(  # type: ignore[arg-type]
        _mat4_mul(_MITSUBA_TO_BLENDER_4, rows),
        _blender_registration_translation(origin_offset),
    )


def matrix_to_legacy_flat(matrix: Sequence[Sequence[float]]) -> list[float]:
    """Serialize a row-major matrix using the existing translation-last flat form."""
    rows = tuple(tuple(float(v) for v in row) for row in matrix)
    if len(rows) != 4 or any(len(row) != 4 for row in rows):
        raise ValueError("matrix must be 4x4")
    return [float(rows[row][col]) for col in range(4) for row in range(4)]


def legacy_flat_to_matrix(values: Sequence[float]) -> Mat4:
    """Read the existing column-major-flat, translation-last camera storage."""
    if len(values) != 16:
        raise ValueError("legacy camera matrix must contain 16 values")
    return tuple(
        tuple(float(values[col * 4 + row]) for col in range(4))
        for row in range(4)
    )  # type: ignore[return-value]


__all__ = [
    "AXIS_TRANSFORM_ID",
    "LEGACY_FLAT_LAYOUT",
    "MATRIX_LAYOUT",
    "TRANSLATION_LAYOUT",
    "CanonicalCameraPose",
    "legacy_flat_to_matrix",
    "matrix_to_legacy_flat",
    "mitsuba_camera_to_blender",
    "mitsuba_point_to_blender",
    "pose_from_mitsuba_camera_to_world",
    "resolve_viewpoint_pose",
]
