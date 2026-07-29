"""Split a multi-material Wavefront OBJ into one sub-OBJ per ``usemtl`` group.

Infinigen exports each asset mesh with several per-face-group materials (a bed =
brushed_metal frame + rough_plastic cushion + wood legs), recorded as multiple
``usemtl`` groups in a single OBJ (dev_report / orphan-material investigation).
The OpticalNav authoring model records only ONE material per object, so the other
groups became "orphan" materials that never rendered — the whole mesh rendered
with a single representative BSDF.

This module lets the render staging emit one Mitsuba ``<shape>`` per material
group (each with its own BSDF), and lets the material viewer enumerate the real
object -> materials relationship. Group material names map to authoring
``material_id`` via :func:`sanitize_material_name` (mirrors ``import_infinigen_scene._san``).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any


def sanitize_material_name(name: str) -> str:
    """Mirror ``apps/import_infinigen_scene._san`` so a ``usemtl`` name maps to the
    same ``material_id`` the importer wrote into authoring_map.materials[]."""
    return re.sub(r"[^0-9A-Za-z._:-]+", "_", str(name)).strip("_") or "x"


def _face_vertex_count(tokens: list[str]) -> int:
    return len(tokens)


def iter_material_groups(obj_path: str | Path) -> list[dict[str, Any]]:
    """Return the ordered ``usemtl`` groups that actually carry faces.

    Each entry: ``{"material_name", "material_id", "face_count", "triangle_count"}``.
    A group with no faces (declared in the .mtl but unused) is omitted — that is the
    common Infinigen case where the object's slot-0 material is never used by a face.
    """
    groups: list[dict[str, Any]] = []
    index: dict[str, dict[str, Any]] = {}
    current: dict[str, Any] | None = None

    def _ensure(name: str) -> dict[str, Any]:
        g = index.get(name)
        if g is None:
            g = {"material_name": name, "face_count": 0, "triangle_count": 0}
            index[name] = g
            groups.append(g)
        return g

    with Path(obj_path).open("r", errors="replace") as fh:
        for line in fh:
            if line.startswith("usemtl "):
                current = _ensure(line[7:].strip())
            elif line.startswith("f "):
                g = current if current is not None else _ensure("__default__")
                verts = line.split()[1:]
                g["face_count"] += 1
                g["triangle_count"] += max(0, _face_vertex_count(verts) - 2)

    result = [g for g in groups if g["face_count"] > 0]
    for g in result:
        g["material_id"] = sanitize_material_name(g["material_name"])
    return result


def _resolve_index(raw: str, total: int) -> int:
    """OBJ index (1-based, negatives relative to current count) -> 0-based."""
    i = int(raw)
    if i < 0:
        return total + i  # -1 -> total-1
    return i - 1


def split_obj_by_material(
    obj_path: str | Path,
    out_dir: str | Path | None = None,
) -> list[dict[str, Any]]:
    """Split ``obj_path`` into one vertex-remapped OBJ per ``usemtl`` group.

    Returns a list of ``{"material_name", "material_id", "path", "triangle_count"}``
    ordered as the groups first appear. Returns ``[]`` when the mesh has <= 1
    non-empty material group (nothing to split; caller keeps the single shape).

    Vertices/uvs/normals are remapped per group so each sub-OBJ only carries the
    data it references (no N x duplication of the full vertex list).
    """
    obj_path = Path(obj_path)
    v: list[str] = []
    vt: list[str] = []
    vn: list[str] = []
    groups: list[dict[str, Any]] = []
    index: dict[str, dict[str, Any]] = {}
    current: dict[str, Any] | None = None

    def _ensure(name: str) -> dict[str, Any]:
        g = index.get(name)
        if g is None:
            g = {"material_name": name, "faces": []}
            index[name] = g
            groups.append(g)
        return g

    with obj_path.open("r", errors="replace") as fh:
        for line in fh:
            if line.startswith("v "):
                v.append(line.rstrip("\n"))
            elif line.startswith("vt "):
                vt.append(line.rstrip("\n"))
            elif line.startswith("vn "):
                vn.append(line.rstrip("\n"))
            elif line.startswith("usemtl "):
                current = _ensure(line[7:].strip())
            elif line.startswith("f "):
                g = current if current is not None else _ensure("__default__")
                g["faces"].append(line.split()[1:])

    nonempty = [g for g in groups if g["faces"]]
    if len(nonempty) <= 1:
        return []

    out_dir = Path(out_dir) if out_dir is not None else obj_path.parent / "_split"
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = obj_path.stem

    results: list[dict[str, Any]] = []
    for g in nonempty:
        mat_id = sanitize_material_name(g["material_name"])
        # Per-group vertex/uv/normal remap: collect used originals, assign new ids.
        vmap: dict[int, int] = {}
        vtmap: dict[int, int] = {}
        vnmap: dict[int, int] = {}
        out_faces: list[str] = []
        tri = 0
        for verts in g["faces"]:
            new_tokens: list[str] = []
            for tok in verts:
                parts = tok.split("/")
                vi = _resolve_index(parts[0], len(v))
                if vi not in vmap:
                    vmap[vi] = len(vmap) + 1
                nv = str(vmap[vi])
                nvt = ""
                nvn = ""
                if len(parts) >= 2 and parts[1] != "":
                    ti = _resolve_index(parts[1], len(vt))
                    if ti not in vtmap:
                        vtmap[ti] = len(vtmap) + 1
                    nvt = str(vtmap[ti])
                if len(parts) >= 3 and parts[2] != "":
                    ni = _resolve_index(parts[2], len(vn))
                    if ni not in vnmap:
                        vnmap[ni] = len(vnmap) + 1
                    nvn = str(vnmap[ni])
                if len(parts) == 1:
                    new_tokens.append(nv)
                elif len(parts) == 2:
                    new_tokens.append(f"{nv}/{nvt}")
                else:
                    new_tokens.append(f"{nv}/{nvt}/{nvn}")
            out_faces.append("f " + " ".join(new_tokens))
            tri += max(0, len(verts) - 2)

        # Emit remapped vertex/uv/normal blocks in original order.
        lines: list[str] = [f"# split group: {g['material_name']}"]
        inv_v = sorted(vmap, key=lambda k: vmap[k])
        for oi in inv_v:
            lines.append(v[oi])
        inv_vt = sorted(vtmap, key=lambda k: vtmap[k])
        for oi in inv_vt:
            lines.append(vt[oi])
        inv_vn = sorted(vnmap, key=lambda k: vnmap[k])
        for oi in inv_vn:
            lines.append(vn[oi])
        lines.append(f"usemtl {g['material_name']}")
        lines.extend(out_faces)

        sub_path = out_dir / f"{stem}__{mat_id}.obj"
        sub_path.write_text("\n".join(lines) + "\n")
        results.append({
            "material_name": g["material_name"],
            "material_id": mat_id,
            "path": sub_path,
            "triangle_count": tri,
        })
    return results
