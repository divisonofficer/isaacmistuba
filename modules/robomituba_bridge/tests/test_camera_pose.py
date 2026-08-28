from __future__ import annotations

import math
from pathlib import Path
import sys
import unittest

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from robomituba_bridge.camera_pose import (  # noqa: E402
    AXIS_TRANSFORM_ID,
    legacy_flat_to_matrix,
    matrix_to_legacy_flat,
    mitsuba_camera_to_blender,
    pose_from_mitsuba_camera_to_world,
    resolve_viewpoint_pose,
)


class CameraPoseTests(unittest.TestCase):
    def test_mitsuba_y_up_to_blender_z_up_origin_and_target(self) -> None:
        pose = resolve_viewpoint_pose([3.5, 3.25, 0.0], 0.0, eye_height_m=1.2)
        self.assertEqual(pose.origin_mitsuba, (3.5, 1.2, 3.25))
        self.assertEqual(pose.target_mitsuba, (3.5, 1.08, 4.25))
        self.assertEqual(pose.origin_blender, (3.5, -3.25, 1.2))
        self.assertEqual(pose.target_blender, (3.5, -4.25, 1.08))
        self.assertEqual(pose.up_blender, (0.0, 0.0, 1.0))
        self.assertEqual(pose.axis_transform, AXIS_TRANSFORM_ID)
        self.assertEqual(pose.provenance()["translation_layout"], "row_major_translation_last_column")
        expected = tuple(
            (pose.target_mitsuba[i] - pose.origin_mitsuba[i])
            / math.sqrt(sum((pose.target_mitsuba[j] - pose.origin_mitsuba[j]) ** 2 for j in range(3)))
            for i in range(3)
        )
        actual = tuple(-pose.camera_to_world_mitsuba[i][2] for i in range(3))
        for lhs, rhs in zip(actual, expected):
            self.assertAlmostEqual(lhs, rhs, places=7)

    def test_infinigen_origin_normalization_registers_back_to_source_blender_world(self) -> None:
        pose = resolve_viewpoint_pose(
            [3.509210380790711, 3.253210044174195, 0.0],
            0.0,
            eye_height_m=1.2,
            target_height_m=1.08,
            origin_offset=[0.8951, 4.6391, -0.1391],
        )
        self.assertAlmostEqual(pose.origin_blender[0], 2.614110380790711, places=7)
        self.assertAlmostEqual(pose.origin_blender[1], 1.385889955825805, places=7)
        self.assertAlmostEqual(pose.origin_blender[2], 1.3391, places=7)
        self.assertAlmostEqual(pose.target_blender[1], 0.385889955825805, places=7)
        self.assertEqual(
            pose.camera_to_world_blender,
            mitsuba_camera_to_blender(
                pose.camera_to_world_mitsuba, origin_offset=[0.8951, 4.6391, -0.1391]
            ),
        )
        self.assertEqual(
            pose.provenance()["authoring_origin_offset"], [0.8951, 4.6391, -0.1391]
        )
        self.assertEqual(
            pose.provenance()["blender_world_registration"], [-0.8951, 4.6391, 0.1391]
        )

    def test_heading_quarter_turns_use_authoring_floor_axes(self) -> None:
        pose = resolve_viewpoint_pose([0.0, 0.0, 0.0], 90.0, eye_height_m=1.2)
        self.assertAlmostEqual(pose.target_mitsuba[0], 1.0, places=7)
        self.assertAlmostEqual(pose.target_mitsuba[2], 0.0, places=7)
        self.assertAlmostEqual(pose.target_blender[0], 1.0, places=7)
        self.assertAlmostEqual(pose.target_blender[1], 0.0, places=7)
        self.assertAlmostEqual(pose.target_blender[2], 1.08, places=7)

    def test_blender_matrix_is_fixed_axis_transform_of_mitsuba_matrix(self) -> None:
        pose = resolve_viewpoint_pose([1.0, 2.0, 0.0], 180.0)
        self.assertEqual(pose.camera_to_world_blender, mitsuba_camera_to_blender(pose.camera_to_world_mitsuba))
        # Blender local -Z maps to the transformed canonical forward vector.
        b = pose.camera_to_world_blender
        forward_b = tuple(-b[row][2] for row in range(3))
        self.assertAlmostEqual(forward_b[0], 0.0, places=7)
        expected_b = tuple(
            pose.target_blender[i] - pose.origin_blender[i] for i in range(3)
        )
        expected_norm = math.sqrt(sum(value * value for value in expected_b))
        for actual, expected in zip(forward_b, expected_b):
            self.assertAlmostEqual(actual, expected / expected_norm, places=7)
        # A camera-to-world basis must remain proper (no reflection).
        r = pose.camera_to_world_mitsuba
        det = (
            r[0][0] * (r[1][1] * r[2][2] - r[1][2] * r[2][1])
            - r[0][1] * (r[1][0] * r[2][2] - r[1][2] * r[2][0])
            + r[0][2] * (r[1][0] * r[2][1] - r[1][1] * r[2][0])
        )
        self.assertAlmostEqual(det, 1.0, places=7)

    def test_legacy_flat_round_trip(self) -> None:
        pose = resolve_viewpoint_pose([2.0, -4.0, 0.0], 45.0)
        flat = matrix_to_legacy_flat(pose.camera_to_world_mitsuba)
        self.assertEqual(legacy_flat_to_matrix(flat), pose.camera_to_world_mitsuba)
        self.assertEqual(flat[12:15], [2.0, 1.2, -4.0])

    def test_resolved_manifest_matrix_materializes_with_provenance(self) -> None:
        source = resolve_viewpoint_pose([3.5, 3.25, 0.0], 90.0)
        pose = pose_from_mitsuba_camera_to_world(
            source.camera_to_world_mitsuba,
            pose_source="observation_manifest",
            target_mitsuba=source.target_mitsuba,
        )
        self.assertEqual(pose.pose_source, "observation_manifest")
        self.assertEqual(pose.origin_blender, source.origin_blender)
        self.assertEqual(pose.target_blender, source.target_blender)
        self.assertAlmostEqual(pose.yaw_deg, 90.0, places=7)

    def test_target_height_is_explicit_and_pitch_is_not_vertical(self) -> None:
        pose = resolve_viewpoint_pose([0.0, 0.0, 0.0], 0.0, eye_height_m=1.2, target_height_m=1.2)
        forward = tuple(pose.target_mitsuba[i] - pose.origin_mitsuba[i] for i in range(3))
        self.assertAlmostEqual(forward[1], 0.0, places=7)
        self.assertAlmostEqual(forward[0], 0.0, places=7)
        self.assertAlmostEqual(forward[2], 1.0, places=7)


if __name__ == "__main__":
    unittest.main()
