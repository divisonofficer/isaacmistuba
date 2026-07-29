"""GLB PBR texture adapter for OpticalNav render assets.

Digital Twin Catalog objects ship as GLB files with embedded PBR textures. The
OpticalNav render path consumes OBJ meshes plus a compact ``extracted_material``
dict, so this module bridges GLB geometry/materials into that existing contract.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping


GLB_TEXTURE_ADAPTER_VERSION = 6


@dataclass
class GlbPart:
    part_id: str
    obj_path: Path
    obj_ref: str
    mesh_name: str
    mesh_prim_path: str
    triangle_count: int
    vertex_count: int
    has_uv: bool
    has_normal: bool
    extracted_material: dict[str, Any] | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "part_id": self.part_id,
            "obj_path": str(self.obj_path),
            "obj_ref": self.obj_ref,
            "mesh_name": self.mesh_name,
            "mesh_prim_path": self.mesh_prim_path,
            "triangle_count": int(self.triangle_count),
            "vertex_count": int(self.vertex_count),
            "has_uv": bool(self.has_uv),
            "has_normal": bool(self.has_normal),
            "extracted_material": self.extracted_material,
        }


@dataclass
class GlbMaterialization:
    source_ref: str
    source_path: str
    digest: str
    status: str
    combined_obj_path: Path | None = None
    combined_obj_ref: str | None = None
    vertex_count: int = 0
    triangle_count: int = 0
    mesh_part_count: int = 0
    has_uv: bool = False
    has_normal: bool = False
    texture_slots: dict[str, int] = field(default_factory=dict)
    mesh_parts: list[GlbPart] = field(default_factory=list)
    error: str | None = None

    def to_meta(self) -> dict[str, Any]:
        return {
            "adapter": "glb_texture_adapter",
            "adapter_version": GLB_TEXTURE_ADAPTER_VERSION,
            "source_ref": self.source_ref,
            "source_path": self.source_path,
            "digest": self.digest,
            "status": self.status,
            "combined_obj_path": str(self.combined_obj_path) if self.combined_obj_path else None,
            "combined_obj_ref": self.combined_obj_ref,
            "vertex_count": int(self.vertex_count),
            "triangle_count": int(self.triangle_count),
            "mesh_part_count": int(self.mesh_part_count),
            "has_uv": bool(self.has_uv),
            "has_normal": bool(self.has_normal),
            "texture_slots": dict(self.texture_slots),
            "mesh_parts": [part.to_dict() for part in self.mesh_parts],
            "error": self.error,
        }


def _safe_slug(value: str, *, fallback: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("._")
    return slug[:80] or fallback


def _rel_or_abs(path: Path, repo_root: Path | None) -> str:
    if repo_root is not None:
        try:
            return path.resolve().relative_to(repo_root.resolve()).as_posix()
        except Exception:
            pass
    return str(path)


def _image_digest_key(glb_path: Path, mtime_ns: int, material_key: str, slot: str, image: Any) -> str:
    size = getattr(image, "size", None)
    mode = getattr(image, "mode", None)
    return hashlib.sha1(f"{glb_path.resolve()}|{mtime_ns}|{material_key}|{slot}|{size}|{mode}|v{GLB_TEXTURE_ADAPTER_VERSION}".encode("utf-8")).hexdigest()[:16]


def _save_embedded_texture(
    image: Any,
    *,
    glb_path: Path,
    mtime_ns: int,
    material_key: str,
    slot: str,
    texture_cache_dir: Path | None,
    repo_root: Path | None,
    record_embedded_refs: bool = False,
) -> str | None:
    if image is None:
        return None
    if texture_cache_dir is None:
        return f"embedded://{material_key}/{slot}" if record_embedded_refs else None
    digest = _image_digest_key(glb_path, mtime_ns, material_key, slot, image)
    texture_cache_dir.mkdir(parents=True, exist_ok=True)
    dst = texture_cache_dir / f"glb_{digest}_{slot}.png"
    if not dst.exists() or dst.stat().st_size == 0:
        tmp = texture_cache_dir / f"glb_{digest}_{slot}.tmp.{os.getpid()}.{threading.get_ident()}.png"
        try:
            img = image.convert("RGB") if hasattr(image, "convert") else image
            img.save(tmp, format="PNG")
            try:
                tmp.replace(dst)
            except FileNotFoundError:
                pass
        except Exception:
            try:
                tmp.unlink(missing_ok=True)
            except Exception:
                pass
            return None
    return _rel_or_abs(dst, repo_root)



def _save_metallic_roughness_channels(
    image: Any,
    *,
    glb_path: Path,
    mtime_ns: int,
    material_key: str,
    texture_cache_dir: Path | None,
    repo_root: Path | None,
    record_embedded_refs: bool = False,
) -> tuple[str | None, str | None]:
    """Materialize glTF packed MR channels (G=roughness, B=metallic)."""
    if image is None:
        return None, None
    try:
        rgb = image.convert("RGB")
        rough = rgb.getchannel("G").convert("RGB")
        metal = rgb.getchannel("B").convert("RGB")
    except Exception:
        return None, None
    rough_ref = _save_embedded_texture(
        rough, glb_path=glb_path, mtime_ns=mtime_ns,
        material_key=material_key, slot="roughness",
        texture_cache_dir=texture_cache_dir, repo_root=repo_root,
        record_embedded_refs=record_embedded_refs,
    )
    metal_ref = _save_embedded_texture(
        metal, glb_path=glb_path, mtime_ns=mtime_ns,
        material_key=material_key, slot="metallic",
        texture_cache_dir=texture_cache_dir, repo_root=repo_root,
        record_embedded_refs=record_embedded_refs,
    )
    return rough_ref, metal_ref

def _material_texture(mat: Any, names: tuple[str, ...]) -> Any | None:
    for name in names:
        try:
            value = getattr(mat, name, None)
        except Exception:
            value = None
        if value is not None:
            return value
    return None


def _material_factor(mat: Any, names: tuple[str, ...]) -> Any | None:
    for name in names:
        try:
            value = getattr(mat, name, None)
        except Exception:
            value = None
        if value is not None:
            return value
    return None


def _color_factor(mat: Any) -> list[float] | None:
    raw = _material_factor(mat, ("baseColorFactor", "base_color_factor"))
    if raw is None:
        raw = getattr(mat, "main_color", None)
        if raw is not None:
            try:
                return [max(0.0, min(1.0, float(c) / 255.0)) for c in list(raw)[:3]]
            except Exception:
                return None
    try:
        vals = list(raw)
        if len(vals) >= 3:
            return [max(0.0, min(1.0, float(c))) for c in vals[:3]]
    except Exception:
        return None
    return None


def _float_factor(mat: Any, names: tuple[str, ...]) -> float | None:
    raw = _material_factor(mat, names)
    if raw is None:
        return None
    try:
        return float(raw)
    except Exception:
        return None


def _extract_material_dict(
    mat: Any,
    *,
    glb_path: Path,
    mtime_ns: int,
    material_key: str,
    texture_cache_dir: Path | None,
    repo_root: Path | None,
    record_embedded_refs: bool = False,
) -> tuple[dict[str, Any] | None, dict[str, int]]:
    if mat is None:
        return None, {}
    slot_counts: dict[str, int] = {}
    base_img = _material_texture(mat, ("baseColorTexture", "base_color_texture", "image"))
    normal_img = _material_texture(mat, ("normalTexture", "normal_texture"))
    mr_img = _material_texture(mat, ("metallicRoughnessTexture", "metallic_roughness_texture"))
    base_ref = _save_embedded_texture(base_img, glb_path=glb_path, mtime_ns=mtime_ns, material_key=material_key, slot="base_color", texture_cache_dir=texture_cache_dir, repo_root=repo_root, record_embedded_refs=record_embedded_refs)
    normal_ref = _save_embedded_texture(normal_img, glb_path=glb_path, mtime_ns=mtime_ns, material_key=material_key, slot="normal", texture_cache_dir=texture_cache_dir, repo_root=repo_root, record_embedded_refs=record_embedded_refs)
    mr_ref = _save_embedded_texture(mr_img, glb_path=glb_path, mtime_ns=mtime_ns, material_key=material_key, slot="metallic_roughness", texture_cache_dir=texture_cache_dir, repo_root=repo_root, record_embedded_refs=record_embedded_refs)
    rough_ref, metallic_ref = _save_metallic_roughness_channels(
        mr_img, glb_path=glb_path, mtime_ns=mtime_ns, material_key=material_key,
        texture_cache_dir=texture_cache_dir, repo_root=repo_root,
        record_embedded_refs=record_embedded_refs,
    )
    if base_ref:
        slot_counts["base_color"] = 1
    if normal_ref:
        slot_counts["normal"] = 1
    if mr_ref:
        slot_counts["metallic_roughness"] = 1
    if rough_ref:
        slot_counts["roughness"] = 1
    if metallic_ref:
        slot_counts["metallic"] = 1
    material_name = str(getattr(mat, "name", "") or material_key)
    em = {
        "source": "glb_pbr",
        "material_id": material_name,
        "surface_shader_id": "glTF.PBR",
        "base_color_factor": _color_factor(mat),
        "base_color_texture_ref": base_ref,
        "normal_texture_ref": normal_ref,
        "metallic_roughness_texture_ref": mr_ref,
        "roughness_texture_ref": rough_ref,
        "metallic_texture_ref": metallic_ref,
        "metallic_factor": _float_factor(mat, ("metallicFactor", "metallic_factor")),
        "roughness_factor": _float_factor(mat, ("roughnessFactor", "roughness_factor")),
    }
    return em, slot_counts


def _mesh_has_uv(mesh: Any) -> bool:
    visual = getattr(mesh, "visual", None)
    uv = getattr(visual, "uv", None)
    try:
        return uv is not None and len(uv) > 0
    except Exception:
        return uv is not None


def _mesh_has_normal(mesh: Any) -> bool:
    try:
        normals = getattr(mesh, "vertex_normals", None)
        return normals is not None and len(normals) > 0
    except Exception:
        return False


def _scene_geometries(loaded: Any) -> list[tuple[str, Any]]:
    geometry = getattr(loaded, "geometry", None)
    graph = getattr(loaded, "graph", None)
    # Bake each geometry's scene-graph node transform into its vertices before export.
    # Infinigen GLBs keep the object's world orientation on the NODE (local geometry
    # differs from the world-oriented .obj the render pipeline expects), so a local
    # export mis-places rotated furniture. Applying the node transform matches the
    # .obj convention; for DTC single-mesh GLBs the transform is identity (no-op).
    if graph is not None and isinstance(geometry, Mapping):
        try:
            nodes = list(graph.nodes_geometry)
        except Exception:
            nodes = []
        out: list[tuple[str, Any]] = []
        for node in nodes:
            try:
                transform, geom_name = graph[node]
            except Exception:
                continue
            mesh = geometry.get(geom_name)
            if mesh is None:
                continue
            try:
                m = mesh.copy()
                m.apply_transform(transform)
            except Exception:
                m = mesh
            out.append((str(geom_name), m))
        if out:
            return out
    if isinstance(geometry, Mapping):
        return [(str(name), mesh) for name, mesh in geometry.items()]
    return [("mesh", loaded)]


def materialize_glb_texture_parts(
    source_ref: str,
    *,
    glb_path: Path,
    repo_root: Path | None,
    mesh_cache_dir: Path,
    texture_cache_dir: Path | None,
    record_embedded_refs: bool = False,
) -> GlbMaterialization:
    """Export GLB geometry/material parts and embedded PBR textures.

    The returned metadata intentionally mirrors USD prim OBJ cache metadata so the
    render daemon can reuse the same part-shape emission path.
    """
    stat = glb_path.stat()
    digest = hashlib.sha1(
        f"{glb_path.resolve()}|{stat.st_mtime_ns}|{stat.st_size}|glb_adapter_v{GLB_TEXTURE_ADAPTER_VERSION}".encode("utf-8")
    ).hexdigest()[:16]
    mesh_cache_dir.mkdir(parents=True, exist_ok=True)
    meta_path = mesh_cache_dir / f"glb_{digest}.meta.json"
    combined_obj = mesh_cache_dir / f"glb_{digest}.obj"
    if meta_path.exists() and combined_obj.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            if int(meta.get("adapter_version") or 0) >= GLB_TEXTURE_ADAPTER_VERSION and meta.get("status") == "ok":
                parts = []
                for raw in meta.get("mesh_parts") or []:
                    obj_path = Path(str(raw.get("obj_path") or ""))
                    if not obj_path.is_absolute() and repo_root is not None:
                        obj_path = repo_root / obj_path
                    parts.append(GlbPart(
                        part_id=str(raw.get("part_id") or ""),
                        obj_path=obj_path,
                        obj_ref=str(raw.get("obj_ref") or _rel_or_abs(obj_path, repo_root)),
                        mesh_name=str(raw.get("mesh_name") or ""),
                        mesh_prim_path=str(raw.get("mesh_prim_path") or ""),
                        triangle_count=int(raw.get("triangle_count") or 0),
                        vertex_count=int(raw.get("vertex_count") or 0),
                        has_uv=bool(raw.get("has_uv")),
                        has_normal=bool(raw.get("has_normal")),
                        extracted_material=raw.get("extracted_material") if isinstance(raw.get("extracted_material"), dict) else None,
                    ))
                return GlbMaterialization(
                    source_ref=source_ref,
                    source_path=str(glb_path),
                    digest=digest,
                    status="ok",
                    combined_obj_path=combined_obj,
                    combined_obj_ref=_rel_or_abs(combined_obj, repo_root),
                    vertex_count=int(meta.get("vertex_count") or 0),
                    triangle_count=int(meta.get("triangle_count") or 0),
                    mesh_part_count=len(parts),
                    has_uv=bool(meta.get("has_uv")),
                    has_normal=bool(meta.get("has_normal")),
                    texture_slots=dict(meta.get("texture_slots") or {}),
                    mesh_parts=parts,
                )
        except Exception:
            pass

    try:
        import trimesh  # type: ignore
    except Exception as exc:
        return GlbMaterialization(source_ref, str(glb_path), digest, "failed", error=f"trimesh_unavailable:{exc}")

    try:
        loaded = trimesh.load(str(glb_path), force="scene")
    except Exception as exc:
        return GlbMaterialization(source_ref, str(glb_path), digest, "failed", error=f"glb_load_failed:{exc}")

    geometries = [(name, mesh) for name, mesh in _scene_geometries(loaded) if hasattr(mesh, "vertices") and hasattr(mesh, "faces")]
    geometries = [(name, mesh) for name, mesh in geometries if len(getattr(mesh, "vertices", [])) > 0 and len(getattr(mesh, "faces", [])) > 0]
    if not geometries:
        return GlbMaterialization(source_ref, str(glb_path), digest, "failed", error="no_geometry")

    try:
        combined = loaded.to_geometry() if hasattr(loaded, "to_geometry") else geometries[0][1]
        if hasattr(combined, "vertices") and hasattr(combined, "faces"):
            # Keep the GLB's vertex normals in the intermediate OBJ.  Without
            # this explicit flag trimesh may omit ``vn`` when its cache has not
            # been populated; the resulting duplicated UV-corner vertices then
            # render flat per triangle and expose triangulation seams.
            combined.export(str(combined_obj), file_type="obj", include_normals=True)
    except Exception:
        combined_obj = None  # type: ignore[assignment]

    part_dir = mesh_cache_dir / f"glb_{digest}_parts"
    part_dir.mkdir(parents=True, exist_ok=True)
    parts: list[GlbPart] = []
    texture_slots: dict[str, int] = {}
    total_vertices = 0
    total_faces = 0
    any_uv = False
    any_normal = False
    for index, (name, mesh) in enumerate(geometries):
        slug = _safe_slug(name, fallback=f"part_{index:03d}")
        part_path = part_dir / f"{index:03d}_{slug}.obj"
        try:
            mesh.export(str(part_path), file_type="obj", include_normals=True)
        except Exception:
            continue
        material = getattr(getattr(mesh, "visual", None), "material", None)
        material_key = f"{index}_{getattr(material, 'name', '') or slug}"
        em, slots = _extract_material_dict(
            material,
            glb_path=glb_path,
            mtime_ns=stat.st_mtime_ns,
            material_key=material_key,
            texture_cache_dir=texture_cache_dir,
            repo_root=repo_root,
            record_embedded_refs=record_embedded_refs,
        )
        for key, value in slots.items():
            texture_slots[key] = texture_slots.get(key, 0) + value
        vertex_count = int(len(getattr(mesh, "vertices", [])))
        face_count = int(len(getattr(mesh, "faces", [])))
        has_uv = _mesh_has_uv(mesh)
        has_normal = _mesh_has_normal(mesh)
        total_vertices += vertex_count
        total_faces += face_count
        any_uv = any_uv or has_uv
        any_normal = any_normal or has_normal
        parts.append(GlbPart(
            part_id=f"part_{index:03d}_{slug}",
            obj_path=part_path,
            obj_ref=_rel_or_abs(part_path, repo_root),
            mesh_name=name,
            mesh_prim_path=f"/GLB/{slug}",
            triangle_count=face_count,
            vertex_count=vertex_count,
            has_uv=has_uv,
            has_normal=has_normal,
            extracted_material=em,
        ))

    if not parts:
        return GlbMaterialization(source_ref, str(glb_path), digest, "failed", error="part_export_failed")

    result = GlbMaterialization(
        source_ref=source_ref,
        source_path=str(glb_path),
        digest=digest,
        status="ok",
        combined_obj_path=combined_obj if isinstance(combined_obj, Path) else parts[0].obj_path,
        combined_obj_ref=_rel_or_abs(combined_obj if isinstance(combined_obj, Path) else parts[0].obj_path, repo_root),
        vertex_count=total_vertices,
        triangle_count=total_faces,
        mesh_part_count=len(parts),
        has_uv=any_uv,
        has_normal=any_normal,
        texture_slots=texture_slots,
        mesh_parts=parts,
    )
    try:
        meta_path.write_text(json.dumps(result.to_meta(), ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass
    return result


def extract_glb_mesh_for_editor(glb_path: Path, *, max_triangles: int = 3500) -> dict[str, Any] | None:
    """Return a compact triangle mesh payload for editor previews/thumbnails.

    This intentionally mirrors ``extract_prim_mesh_for_editor`` from the USD path:
    flat vertex/index arrays plus simple bounds. It uses the scene-combined GLB
    geometry so newly placed DTC assets can render in the editor before the
    full Mitsuba render-scene materialization cache exists.
    """
    try:
        import numpy as np  # type: ignore
        import trimesh  # type: ignore
    except Exception:
        return None
    try:
        loaded = trimesh.load(str(glb_path), force="scene")
        mesh = loaded.to_geometry() if hasattr(loaded, "to_geometry") else loaded
    except Exception:
        return None
    if not hasattr(mesh, "vertices") or not hasattr(mesh, "faces"):
        return None
    try:
        vertices = np.asarray(mesh.vertices, dtype=np.float32)
        faces = np.asarray(mesh.faces, dtype=np.int64)
    except Exception:
        return None
    if vertices.ndim != 2 or vertices.shape[1] != 3 or faces.ndim != 2 or faces.shape[1] != 3:
        return None
    if len(vertices) == 0 or len(faces) == 0:
        return None
    finite_vertices = np.isfinite(vertices).all(axis=1)
    if not finite_vertices.all():
        valid_faces = finite_vertices[faces].all(axis=1)
        faces = faces[valid_faces]
        if len(faces) == 0:
            return None
    if max_triangles > 0 and len(faces) > max_triangles:
        # Deterministic decimation by even face sampling. This is preview-only,
        # so preserving global silhouette is more valuable than exact topology.
        take = np.linspace(0, len(faces) - 1, max_triangles, dtype=np.int64)
        faces = faces[take]
    used = np.unique(faces.reshape(-1))
    if len(used) == 0:
        return None
    remap = np.full(len(vertices), -1, dtype=np.int64)
    remap[used] = np.arange(len(used), dtype=np.int64)
    compact_vertices = vertices[used]
    compact_faces = remap[faces]
    mn = compact_vertices.min(axis=0)
    mx = compact_vertices.max(axis=0)
    size = np.maximum(mx - mn, 1e-6)
    center = (mn + mx) * 0.5
    return {
        "source_format": "glb",
        "vertices": np.round(compact_vertices.reshape(-1), 6).astype(float).tolist(),
        "indices": compact_faces.reshape(-1).astype(int).tolist(),
        "bounds": {
            "min": np.round(mn, 6).astype(float).tolist(),
            "max": np.round(mx, 6).astype(float).tolist(),
            "center": np.round(center, 6).astype(float).tolist(),
            "size": np.round(size, 6).astype(float).tolist(),
        },
        "triangle_count": int(len(compact_faces)),
        "source_triangle_count": int(len(np.asarray(mesh.faces))),
    }
