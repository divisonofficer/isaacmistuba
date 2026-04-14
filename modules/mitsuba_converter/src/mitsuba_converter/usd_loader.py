from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional
import numpy as np

from .types import MeshData, SceneIR


@dataclass
class UsdSceneLoader:
    """Loads USD stage and extracts minimal geometry IR.

    Note: This module expects Pixar USD Python bindings (pxr) to be available.
    In Isaac Sim Python, pxr is typically available.
    """

    usd_path: str

    def load(self) -> SceneIR:
        try:
            from pxr import Usd, UsdGeom
        except Exception as e:
            raise RuntimeError(
                "USD Python bindings (pxr) not found. Run this inside Isaac Sim Python or install USD."
            ) from e

        stage = Usd.Stage.Open(self.usd_path)
        if stage is None:
            raise RuntimeError(f"Failed to open USD stage: {self.usd_path}")

        meshes: List[MeshData] = []

        # MVP: extract first few UsdGeom.Mesh prims (no instancing/materials yet)
        for prim in stage.Traverse():
            if not prim.IsA(UsdGeom.Mesh):
                continue

            mesh = UsdGeom.Mesh(prim)
            points = mesh.GetPointsAttr().Get() or []
            counts = mesh.GetFaceVertexCountsAttr().Get() or []
            indices = mesh.GetFaceVertexIndicesAttr().Get() or []

            if len(points) == 0 or len(counts) == 0 or len(indices) == 0:
                continue

            # triangulate naively (fan) for MVP
            tri_faces = []
            cursor = 0
            for c in counts:
                face = indices[cursor:cursor+c]
                cursor += c
                if c < 3:
                    continue
                # fan triangulation
                v0 = face[0]
                for k in range(1, c-1):
                    tri_faces.append([v0, face[k], face[k+1]])

            if not tri_faces:
                continue

            v = np.asarray([(p[0], p[1], p[2]) for p in points], dtype=np.float32)
            f = np.asarray(tri_faces, dtype=np.int32)

            meshes.append(MeshData(name=str(prim.GetPath()), vertices=v, faces=f))

            # keep MVP small by default
            if len(meshes) >= 20:
                break

        return SceneIR(meshes=meshes)
