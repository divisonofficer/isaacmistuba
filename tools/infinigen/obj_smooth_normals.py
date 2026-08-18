#!/usr/bin/env python3
"""Create an explicit smooth-by-angle OBJ normal variant without changing UVs.

This is a QA/canonicalization tool, not a repair applied implicitly by the GLB
adapter.  It welds position-equivalent corners only for normal averaging while
retaining the original independent OBJ position and texture-coordinate indices.
"""
from __future__ import annotations

import argparse
import math
from pathlib import Path

import numpy as np


def _face_token(token: str) -> tuple[int, int | None]:
    fields = token.split("/")
    return int(fields[0]), int(fields[1]) if len(fields) > 1 and fields[1] else None


def smooth_obj_normals(source: Path, output: Path, *, angle_degrees: float = 45.0,
                       weld_tolerance: float = 1e-6) -> dict:
    lines = source.read_text(encoding="utf-8", errors="ignore").splitlines()
    vertices = np.asarray([
        [float(value) for value in line.split()[1:4]]
        for line in lines if line.startswith("v ")
    ], np.float64)
    face_line_indices = []
    faces = []
    texcoords = []
    for line_index, line in enumerate(lines):
        if not line.startswith("f "):
            continue
        tokens = line.split()[1:]
        if len(tokens) != 3:
            raise ValueError(f"triangulated OBJ required, got {len(tokens)} corners")
        parsed = [_face_token(token) for token in tokens]
        faces.append([item[0] - 1 for item in parsed])
        texcoords.append([item[1] for item in parsed])
        face_line_indices.append(line_index)
    faces_array = np.asarray(faces, np.int64)
    if not len(vertices) or not len(faces_array):
        raise ValueError("OBJ has no triangle geometry")

    points = vertices[faces_array]
    raw_normals = np.cross(points[:, 1] - points[:, 0], points[:, 2] - points[:, 0])
    doubled_area = np.linalg.norm(raw_normals, axis=1)
    face_normals = raw_normals / np.maximum(doubled_area[:, None], 1e-20)
    quantized = np.rint(vertices / float(weld_tolerance)).astype(np.int64)
    weld_ids = [tuple(row) for row in quantized]
    adjacency: dict[tuple[int, int, int], list[int]] = {}
    for face_index, face in enumerate(faces_array):
        for vertex_index in face:
            adjacency.setdefault(weld_ids[int(vertex_index)], []).append(face_index)

    threshold = math.cos(math.radians(float(angle_degrees)))
    corner_normals = []
    for face_index, face in enumerate(faces_array):
        reference = face_normals[face_index]
        for vertex_index in face:
            candidates = np.asarray(adjacency[weld_ids[int(vertex_index)]], np.int64)
            compatible = candidates[(face_normals[candidates] @ reference) >= threshold]
            weights = doubled_area[compatible]
            normal = np.sum(face_normals[compatible] * weights[:, None], axis=0)
            length = float(np.linalg.norm(normal))
            corner_normals.append(normal / max(length, 1e-20))

    first_face = min(face_line_indices)
    face_lookup = {line_index: face_index for face_index, line_index in enumerate(face_line_indices)}
    emitted = []
    inserted_normals = False
    for line_index, line in enumerate(lines):
        if line.startswith("vn "):
            continue
        if line_index == first_face and not inserted_normals:
            emitted.extend(
                f"vn {normal[0]:.9g} {normal[1]:.9g} {normal[2]:.9g}"
                for normal in corner_normals
            )
            inserted_normals = True
        if line_index not in face_lookup:
            emitted.append(line)
            continue
        face_index = face_lookup[line_index]
        tokens = []
        for corner, (vertex_index, texture_index) in enumerate(
            zip(faces_array[face_index], texcoords[face_index])
        ):
            normal_index = face_index * 3 + corner + 1
            texture = "" if texture_index is None else str(texture_index)
            tokens.append(f"{int(vertex_index) + 1}/{texture}/{normal_index}")
        emitted.append("f " + " ".join(tokens))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(emitted) + "\n", encoding="utf-8")
    return {
        "source": str(source.resolve()),
        "output": str(output.resolve()),
        "vertex_count": int(len(vertices)),
        "triangle_count": int(len(faces_array)),
        "corner_normal_count": int(len(corner_normals)),
        "angle_degrees": float(angle_degrees),
        "weld_tolerance": float(weld_tolerance),
        "normal_source": "position_welded_area_weighted_smooth_by_angle",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--angle", type=float, default=45.0)
    parser.add_argument("--weld-tolerance", type=float, default=1e-6)
    args = parser.parse_args()
    print(smooth_obj_normals(
        args.source, args.output, angle_degrees=args.angle,
        weld_tolerance=args.weld_tolerance,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
