from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional
import numpy as np

Mat4 = np.ndarray  # shape (4,4)


@dataclass
class MeshData:
    name: str
    vertices: np.ndarray          # (N,3) float32
    faces: np.ndarray             # (M,3) int32 (triangulated)
    normals: Optional[np.ndarray] = None  # (N,3) or (M,3)
    uvs: Optional[np.ndarray] = None      # (N,2) or (M,2)
    to_world: Optional[Mat4] = None

@dataclass
class SceneIR:
    """Legacy mesh-only IR kept for backward-compatible USD conversion paths.

    New bridge-facing flows should use robomituba_bridge.SceneSnapshot instead.
    """

    meshes: List[MeshData]
    # Deprecated as the primary boundary. Snapshot/manifest is the new contract.
