from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional
import numpy as np

from .types import MeshData, SceneIR
from .usd_snapshot import extract_snapshot_from_usd


@dataclass
class UsdSceneLoader:
    """Loads USD stage and extracts minimal geometry IR.

    Note: This module expects Pixar USD Python bindings (pxr) to be available.
    In Isaac Sim Python, pxr is typically available.
    """

    usd_path: str

    def load(self) -> SceneIR:
        meshes: List[MeshData] = []
        extracted = extract_snapshot_from_usd(self.usd_path, include_geometry_payloads=True)
        for mesh_record in extracted.snapshot.meshes:
            geometry = mesh_record.extras.get("geometry") if isinstance(mesh_record.extras, dict) else None
            if not isinstance(geometry, dict):
                continue
            vertices = geometry.get("vertices") or []
            faces = geometry.get("faces") or []
            if not vertices or not faces:
                continue
            normals = geometry.get("normals")
            uvs = geometry.get("uvs")
            meshes.append(
                MeshData(
                    name=mesh_record.source_path,
                    vertices=np.asarray(vertices, dtype=np.float32),
                    faces=np.asarray(faces, dtype=np.int32),
                    normals=np.asarray(normals, dtype=np.float32) if normals else None,
                    uvs=np.asarray(uvs, dtype=np.float32) if uvs else None,
                    to_world=np.asarray(mesh_record.transform, dtype=np.float32).reshape(4, 4)
                    if mesh_record.transform else None,
                )
            )

        return SceneIR(meshes=meshes)
