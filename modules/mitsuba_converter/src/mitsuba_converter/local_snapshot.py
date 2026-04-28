"""Offline SceneSnapshot builder from a Mitsuba XML file.

Used when Isaac Sim is unavailable but the scene already has a Mitsuba XML +
OBJ geometry on disk. Parses <shape> elements, composes <transform> children
into a 4x4 matrix, and emits a minimal SceneSnapshot + shape_map so the
3D Blueprint view (driven by mesh bounds) can render without Isaac.
"""
from __future__ import annotations

import json
import math
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from robomituba_bridge import (
    FrameRecord,
    MeshRecord,
    SceneSnapshot,
    resolve_repo_path,
    to_repo_relative_posix,
)
from robomituba_bridge.io import scene_snapshot_to_payload
from robomituba_bridge.shape_mapping import build_shape_mapping, write_shape_mapping


Mat4 = list[float]
IDENTITY_4x4: Mat4 = [1.0, 0.0, 0.0, 0.0,
                     0.0, 1.0, 0.0, 0.0,
                     0.0, 0.0, 1.0, 0.0,
                     0.0, 0.0, 0.0, 1.0]


def _floats(raw: str | None, *, count: int | None = None) -> list[float]:
    if not raw:
        return []
    parts: list[float] = []
    for token in raw.replace(",", " ").split():
        try:
            parts.append(float(token))
        except ValueError:
            continue
    if count is not None and len(parts) != count:
        return []
    return parts


def _mat_mul(a: Mat4, b: Mat4) -> Mat4:
    # Both treated as row-major 4x4 (consistent with MeshRecord.transform usage downstream).
    out = [0.0] * 16
    for i in range(4):
        for j in range(4):
            s = 0.0
            for k in range(4):
                s += a[i * 4 + k] * b[k * 4 + j]
            out[i * 4 + j] = s
    return out


def _translate_matrix(x: float, y: float, z: float) -> Mat4:
    m = list(IDENTITY_4x4)
    m[3], m[7], m[11] = x, y, z
    return m


def _scale_matrix(x: float, y: float, z: float) -> Mat4:
    return [
        x,   0.0, 0.0, 0.0,
        0.0, y,   0.0, 0.0,
        0.0, 0.0, z,   0.0,
        0.0, 0.0, 0.0, 1.0,
    ]


def _rotate_matrix(axis: str, angle_deg: float) -> Mat4:
    c = math.cos(math.radians(angle_deg))
    s = math.sin(math.radians(angle_deg))
    ax = (axis or "y").lower()
    if ax == "x":
        return [
            1.0, 0.0, 0.0, 0.0,
            0.0, c,  -s,   0.0,
            0.0, s,   c,   0.0,
            0.0, 0.0, 0.0, 1.0,
        ]
    if ax == "z":
        return [
             c,  -s,  0.0, 0.0,
             s,   c,  0.0, 0.0,
            0.0, 0.0, 1.0, 0.0,
            0.0, 0.0, 0.0, 1.0,
        ]
    return [
         c,  0.0,  s,  0.0,
        0.0, 1.0, 0.0, 0.0,
        -s,  0.0,  c,  0.0,
        0.0, 0.0, 0.0, 1.0,
    ]


def _lookat_matrix(origin: list[float], target: list[float], up: list[float]) -> Mat4:
    if len(origin) != 3 or len(target) != 3 or len(up) != 3:
        return list(IDENTITY_4x4)

    def sub(a, b): return [a[0] - b[0], a[1] - b[1], a[2] - b[2]]
    def cross(a, b): return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]
    def norm(v):
        m = math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2]) or 1.0
        return [v[0] / m, v[1] / m, v[2] / m]

    f = norm(sub(target, origin))
    s = norm(cross(f, norm(up)))
    u = cross(s, f)
    return [
         s[0],  u[0], -f[0], origin[0],
         s[1],  u[1], -f[1], origin[1],
         s[2],  u[2], -f[2], origin[2],
         0.0,   0.0,  0.0,   1.0,
    ]


def _compose_to_world(transform_el: ET.Element | None) -> Mat4:
    """Walk <transform> children in XML order, composing left-to-right (m = m @ child)."""
    if transform_el is None:
        return list(IDENTITY_4x4)
    m: Mat4 = list(IDENTITY_4x4)
    for child in list(transform_el):
        tag = child.tag.lower()
        if tag == "matrix":
            values = _floats(child.attrib.get("value"), count=16)
            if len(values) == 16:
                m = _mat_mul(m, values)
        elif tag == "translate":
            x = float(child.attrib.get("x", 0) or 0)
            y = float(child.attrib.get("y", 0) or 0)
            z = float(child.attrib.get("z", 0) or 0)
            vec = _floats(child.attrib.get("value"), count=3)
            if vec:
                x, y, z = vec[0], vec[1], vec[2]
            m = _mat_mul(m, _translate_matrix(x, y, z))
        elif tag == "scale":
            if "value" in child.attrib:
                vals = _floats(child.attrib.get("value"))
                if len(vals) == 1:
                    x = y = z = vals[0]
                elif len(vals) >= 3:
                    x, y, z = vals[0], vals[1], vals[2]
                else:
                    x = y = z = 1.0
            else:
                x = float(child.attrib.get("x", 1) or 1)
                y = float(child.attrib.get("y", 1) or 1)
                z = float(child.attrib.get("z", 1) or 1)
            m = _mat_mul(m, _scale_matrix(x, y, z))
        elif tag == "rotate":
            angle = float(child.attrib.get("angle", 0) or 0)
            if "axis" in child.attrib:
                axis_name = child.attrib["axis"]
            else:
                for axis in ("x", "y", "z"):
                    if axis in child.attrib and float(child.attrib.get(axis, 0) or 0) != 0.0:
                        axis_name = axis
                        break
                else:
                    axis_name = "y"
            m = _mat_mul(m, _rotate_matrix(axis_name, angle))
        elif tag == "lookat":
            origin = _floats(child.attrib.get("origin"), count=3)
            target = _floats(child.attrib.get("target"), count=3)
            up = _floats(child.attrib.get("up"), count=3) or [0.0, 1.0, 0.0]
            if origin and target:
                m = _mat_mul(m, _lookat_matrix(origin, target, up))
    return m


def _shape_filename(shape: ET.Element) -> str | None:
    for string_node in shape.findall("./string"):
        if string_node.attrib.get("name") == "filename":
            return string_node.attrib.get("value") or None
    return None


def _to_repo_relative(repo_root: Path, raw: str) -> str:
    candidate = Path(raw)
    if candidate.is_absolute():
        try:
            return to_repo_relative_posix(repo_root, candidate)
        except Exception:
            return raw.replace("\\", "/")
    return raw.replace("\\", "/")


def build_snapshot_from_mitsuba_xml(
    scene_id: str,
    xml_path: Path,
    repo_root: Path,
) -> tuple[SceneSnapshot, int]:
    """Return (snapshot, skipped_primitive_count) built from Mitsuba XML shapes."""
    root = ET.parse(xml_path).getroot()
    meshes: list[MeshRecord] = []
    skipped_primitives = 0
    for index, shape in enumerate(root.findall("./shape")):
        if shape.find("./emitter") is not None:
            continue  # area light; no renderable geometry
        filename = _shape_filename(shape)
        if not filename:
            skipped_primitives += 1
            continue
        shape_id = shape.attrib.get("id") or f"shape_{index:04d}"
        transform_el = shape.find("./transform[@name='to_world']") or shape.find("./transform")
        transform = _compose_to_world(transform_el)
        geometry_path = _to_repo_relative(repo_root, filename)
        meshes.append(
            MeshRecord(
                mesh_id=shape_id,
                name=shape_id,
                source_path=f"/xml/{shape_id}",
                material_id=None,
                geometry_path=geometry_path,
                primitive=(shape.attrib.get("type") or "mesh"),
                transform=transform,
                extras={"mitsuba_shape_type": shape.attrib.get("type") or "mesh"},
            )
        )
    snapshot = SceneSnapshot(
        scene_id=scene_id,
        frame=FrameRecord(frame_id="local_v1", time_code=0.0),
        meshes=meshes,
        extras={"local_snapshot_source": "mitsuba_xml_v1"},
    )
    return snapshot, skipped_primitives


def enumerate_xml_targets(xml_path: Path) -> list[dict[str, Any]]:
    """Return per-`<shape>` semantic context for an LLM/agent to match BRDFs.

    Each entry exposes the strongest semantic signals the agent can read:
    the shape id, geometry filename, current inline BSDF summary (type +
    roughness/metallic/ior + the texture filenames it references). Shapes
    that contain an ``<emitter>`` child (area lights) are flagged so the
    agent can skip them.
    """
    root = ET.parse(xml_path).getroot()
    targets: list[dict[str, Any]] = []
    for index, shape in enumerate(root.findall("./shape")):
        shape_id = shape.attrib.get("id") or f"shape_{index:04d}"
        primitive = shape.attrib.get("type") or "mesh"
        filename = _shape_filename(shape)
        embedded_emitter = shape.find("./emitter") is not None
        targets.append(
            {
                "shape_id": shape_id,
                "primitive": primitive,
                "geometry_file": filename,
                "embedded_emitter": embedded_emitter,
                "current_bsdf": _summarize_bsdf(shape),
            }
        )
    return targets


def _summarize_bsdf(shape: ET.Element) -> dict[str, Any] | None:
    """Condense the inline ``<bsdf>`` of a shape into LLM-friendly fields."""
    bsdf_el = shape.find("./bsdf")
    if bsdf_el is None:
        return None
    # Unwrap a ``twosided`` wrapper so the agent sees the inner BSDF directly.
    inner = bsdf_el
    while inner.attrib.get("type") == "twosided":
        child = inner.find("./bsdf")
        if child is None:
            break
        inner = child
    summary: dict[str, Any] = {"type": inner.attrib.get("type") or "unknown"}
    for float_el in inner.findall("./float"):
        name = float_el.attrib.get("name")
        if not name:
            continue
        try:
            summary[name] = float(float_el.attrib.get("value", "") or 0.0)
        except ValueError:
            continue
    rgb_el = inner.find("./rgb[@name='base_color']")
    if rgb_el is not None and rgb_el.attrib.get("value"):
        summary["base_color"] = rgb_el.attrib.get("value")
    # Texture references — filenames carry strong semantic signal
    # ("baseFloorsd_diffuse.png" → wood floor).
    texture_filenames: list[dict[str, str]] = []
    for tex_el in inner.findall(".//texture"):
        slot = tex_el.attrib.get("name") or "unknown"
        for string_el in tex_el.findall("./string"):
            if string_el.attrib.get("name") == "filename":
                value = string_el.attrib.get("value") or ""
                if value:
                    texture_filenames.append(
                        {"slot": slot, "filename": Path(value).name, "path": value.replace("\\", "/")}
                    )
    if texture_filenames:
        summary["textures"] = texture_filenames
    return summary


def write_local_snapshot(
    snapshot: SceneSnapshot,
    *,
    output_path: Path,
    repo_root: Path,
) -> Path:
    payload = scene_snapshot_to_payload(snapshot)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return output_path


def prepare_basic_scene_from_disk(
    scene_id: str,
    *,
    mitsuba_scene_ref: str,
    repo_root: Path,
) -> dict[str, Any]:
    """Build a SceneSnapshot + shape_map from the Mitsuba XML on disk.

    Returns a dict with repo-relative refs and counts, suitable for re-registering
    the scene via RenderDaemon._register_isaac_scene.
    """
    repo_root = Path(repo_root).resolve()
    xml_path = resolve_repo_path(repo_root, mitsuba_scene_ref)
    if not xml_path.exists():
        raise FileNotFoundError(f"Mitsuba scene XML not found: {mitsuba_scene_ref}")

    snapshot, skipped_primitives = build_snapshot_from_mitsuba_xml(scene_id, xml_path, repo_root)

    snapshot_output = xml_path.with_name(f"{xml_path.stem}.scene_snapshot.json")
    write_local_snapshot(snapshot, output_path=snapshot_output, repo_root=repo_root)
    scene_snapshot_ref = to_repo_relative_posix(repo_root, snapshot_output)

    mapping = build_shape_mapping(snapshot, xml_path)
    shape_map_output = xml_path.with_name(f"{xml_path.stem}.shape_map.json")
    write_shape_mapping(
        shape_map_output,
        mapping_payload=mapping,
        repo_root=repo_root,
        scene_xml_ref=mitsuba_scene_ref,
        scene_snapshot_ref=scene_snapshot_ref,
    )
    shape_map_ref = to_repo_relative_posix(repo_root, shape_map_output)

    prim_to_shape_ids = mapping.get("prim_to_shape_ids") or {}
    unmatched = mapping.get("unmatched_prim_paths") or []
    return {
        "scene_snapshot_ref": scene_snapshot_ref,
        "shape_map_ref": shape_map_ref,
        "mesh_count": len(snapshot.meshes),
        "shape_count": int(mapping.get("shape_count") or 0),
        "matched": len(prim_to_shape_ids),
        "unmatched": len(unmatched),
        "skipped_primitives": skipped_primitives,
    }
