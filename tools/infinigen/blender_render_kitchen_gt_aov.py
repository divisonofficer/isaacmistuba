#!/usr/bin/env python3
"""Kitchen-only Blender GT exporter with reachable, packed PBR AOVs.

This wrapper keeps the existing camera/graph/render contract but replaces the
old ``VALUE`` AOV and ``principled[0]`` shortcut.  It resolves the material
output surface, follows nested shader groups, and handles a reducible
``Mix Shader`` of Principled closures.  Every material emits one packed
``GT_PBR_PARAMS`` Color AOV:

    R = roughness, G = metallic, B = canonicalizable/valid (0 or 1)

``GT_BASE_COLOR`` remains a separate Color AOV.  Layered or non-Principled
closures that cannot be reduced to these channels are retained in the report
and receive validity=0; they are never silently presented as exact PBR GT.

Run with the bundled Blender, for example::

  python tools/infinigen/run_bundled_blender.py --background kitchen.blend \
    --python tools/infinigen/blender_render_kitchen_gt_aov.py -- \
    --scene-graph out/.../viewpoint_graph.json --viewpoints vp_000005@180 \
    --out /tmp/kitchen_gt_probe

If ``--viewpoints`` is omitted, every graph node heading is rendered (for the
kitchen graph this is 71 nodes × 24 headings = 1704 frames).
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

import bpy  # type: ignore

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import blender_render_gt_aov as _base  # noqa: E402
from blender_audit_original_pbr import _material_audit  # noqa: E402

# main monkey-patches the base exporter for its kitchen-specific AOVs.
# Keep this original collector so the wrapper can delegate without recursion.
_BASE_COLLECT_OUTPUTS = _base._collect_outputs


_AOVS = {
    "GT_BASE_COLOR": "color",
    "GT_PBR_PARAMS": "color",
    "GT_MaterialID": "value",
}
_CHANNEL_INPUTS = {
    "base_color": ("Base Color",),
    "roughness": ("Roughness",),
    "metallic": ("Metallic",),
}
_REPORT: list[dict] = []
_INTERFACES: list[tuple[object, object]] = []


def _socket(node, *names):
    for name in names:
        try:
            value = node.inputs.get(name) or node.outputs.get(name)
        except Exception:
            value = None
        if value is not None:
            return value
    return None


def _interface_socket(tree, name: str, *, color: bool = False):
    interface = getattr(tree, "interface", None)
    if interface is None:
        return None, False
    for item in getattr(interface, "items_tree", ()):  # Blender 4.x
        if getattr(item, "item_type", None) == "SOCKET" and getattr(item, "in_out", None) == "OUTPUT" and item.name == name:
            return item, False
    item = interface.new_socket(name=name, in_out="OUTPUT", socket_type="NodeSocketColor" if color else "NodeSocketFloat")
    _INTERFACES.append((tree, item))
    return item, True


def _group_output_input(tree, output_socket):
    for node in tree.nodes:
        if node.type != "GROUP_OUTPUT":
            continue
        for candidate in node.inputs:
            if candidate.identifier == getattr(output_socket, "identifier", None) or candidate.name == output_socket.name:
                return candidate
    return None


def _group_output_node(tree):
    return next((node for node in tree.nodes if node.type == "GROUP_OUTPUT"), None)


def _new_value(tree, value, created, *, color: bool = False):
    if color:
        node = tree.nodes.new("ShaderNodeRGB")
        raw = getattr(value, "default_value", value)
        if isinstance(raw, (int, float)):
            raw = (float(raw), float(raw), float(raw), 1.0)
        node.outputs[0].default_value = tuple(raw[:4])
    else:
        node = tree.nodes.new("ShaderNodeValue")
        raw = getattr(value, "default_value", value)
        if isinstance(raw, (tuple, list)):
            raw = raw[0] if raw else 0.0
        node.outputs[0].default_value = float(raw)
    created.append((tree, node))
    return node.outputs[0]


def _input_expr(socket, created, *, color: bool = False):
    if socket is None:
        return {"socket": None, "valid": False, "source": "missing"}
    if socket.is_linked:
        link = socket.links[0]
        return {"socket": link.from_socket, "valid": True, "source": f"linked:{link.from_node.type}:{link.from_socket.name}"}
    return {"socket": _new_value(socket.id_data, socket, created, color=color), "valid": True, "source": "constant"}


def _invalid(source: str):
    return {"socket": None, "valid": False, "source": source}


def _mix_expr(tree, factor, left, right, channel: str, created):
    if not factor["socket"] or not left["socket"] or not right["socket"]:
        return _invalid("mix_missing_input")
    if channel == "base_color":
        node = tree.nodes.new("ShaderNodeMixRGB")
        node.blend_type = "MIX"
        node.inputs[0].default_value = 0.0
        tree.links.new(factor["socket"], node.inputs[0])
        tree.links.new(left["socket"], node.inputs[1])
        tree.links.new(right["socket"], node.inputs[2])
        created.append((tree, node))
        return {"socket": node.outputs[0], "valid": left["valid"] and right["valid"], "source": "mix_shader"}
    one_minus = tree.nodes.new("ShaderNodeMath")
    one_minus.operation = "SUBTRACT"
    one_minus.inputs[0].default_value = 1.0
    tree.links.new(factor["socket"], one_minus.inputs[1])
    a_mul = tree.nodes.new("ShaderNodeMath")
    a_mul.operation = "MULTIPLY"
    tree.links.new(left["socket"], a_mul.inputs[0])
    tree.links.new(one_minus.outputs[0], a_mul.inputs[1])
    b_mul = tree.nodes.new("ShaderNodeMath")
    b_mul.operation = "MULTIPLY"
    tree.links.new(right["socket"], b_mul.inputs[0])
    tree.links.new(factor["socket"], b_mul.inputs[1])
    add = tree.nodes.new("ShaderNodeMath")
    add.operation = "ADD"
    tree.links.new(a_mul.outputs[0], add.inputs[0])
    tree.links.new(b_mul.outputs[0], add.inputs[1])
    created.extend(((tree, one_minus), (tree, a_mul), (tree, b_mul), (tree, add)))
    return {"socket": add.outputs[0], "valid": left["valid"] and right["valid"], "source": "mix_shader"}


def _ensure_group_adapter(group_node, channel: str, expression, created, cache, stack):
    child = group_node.node_tree
    key = (child.as_pointer(), channel)
    if key in cache:
        return cache[key]
    name = f"__gt_aov_{channel}"
    item, _ = _interface_socket(child, name, color=channel == "base_color")
    output = _group_output_node(child)
    if item is None or output is None or expression["socket"] is None:
        return _invalid("group_adapter_unavailable")
    target = output.inputs.get(name)
    if target is None:
        target = next((candidate for candidate in output.inputs if candidate.identifier == item.identifier), None)
    if target is None:
        return _invalid("group_output_socket_unavailable")
    if not target.is_linked:
        child.links.new(expression["socket"], target)
    exposed = group_node.outputs.get(name)
    if exposed is None:
        exposed = next((candidate for candidate in group_node.outputs if candidate.identifier == item.identifier), None)
    if exposed is None:
        return _invalid("group_instance_output_unavailable")
    result = {"socket": exposed, "valid": expression["valid"], "source": f"group:{group_node.name}"}
    cache[key] = result
    return result


def _resolve_closure(socket, channel: str, created, cache, stack):
    if socket is None or not socket.is_linked:
        return _invalid("surface_unlinked")
    link = socket.links[0]
    node = link.from_node
    tree = node.id_data
    key = (node.as_pointer(), link.from_socket.identifier, channel)
    if key in stack:
        return _invalid("cycle")
    stack.add(key)
    try:
        if node.type == "BSDF_PRINCIPLED":
            source = _socket(node, *_CHANNEL_INPUTS[channel])
            return _input_expr(source, created, color=channel == "base_color")
        if node.type == "MIX_SHADER":
            factor = _input_expr(node.inputs[0], created)
            left = _resolve_closure(node.inputs[1], channel, created, cache, stack)
            right = _resolve_closure(node.inputs[2], channel, created, cache, stack)
            if not left["socket"] or not right["socket"]:
                return _invalid("non_reducible_mix")
            return _mix_expr(tree, factor, left, right, channel, created)
        if node.type == "GROUP" and getattr(node, "node_tree", None):
            target = _group_output_input(node.node_tree, link.from_socket)
            if target is None:
                return _invalid("group_surface_output_missing")
            expression = _resolve_closure(target, channel, created, cache, stack)
            return _ensure_group_adapter(node, channel, expression, created, cache, stack)
        # A non-Principled closure may still expose a color or roughness, but it
        # is not a complete metallic-roughness PBR parameterization. Keep the
        # socket for diagnostics only and force validity=0.
        if node.type in {"BSDF_DIFFUSE", "BSDF_GLOSSY", "BSDF_GLASS"}:
            names = {"base_color": ("Color",), "roughness": ("Roughness",)}.get(channel)
            source = _socket(node, *(names or ()))
            if source is not None:
                expr = _input_expr(source, created, color=channel == "base_color")
                expr["valid"] = False
                expr["source"] = f"non_principled:{node.type}"
                return expr
        return _invalid(f"non_reducible:{node.type}")
    finally:
        stack.discard(key)


def _aov_output(tree, name: str, created, *, kind: str = "color"):
    node = tree.nodes.new("ShaderNodeOutputAOV")
    node.name = f"__gt_kitchen__{name}"
    node.aov_name = name
    created.append((tree, node))
    if kind == "value":
        return node, node.inputs.get("Value") or node.inputs[0]
    return node, node.inputs.get("Color") or node.inputs[0]


def _install_material_aovs(materials: list, material_ids: dict[str, int]):
    created = []
    cache = {}
    for material in materials:
        audit = _material_audit(material)
        row = {
            "blender_material": material.name if material else None,
            "audit_closure": audit.get("closure"),
            "audit_principled_count": audit.get("principled_count", 0),
            "channels": {},
            "resolver": "unresolved",
            "canonicalizable": False,
        }
        _REPORT.append(row)
        tree = material.node_tree if material and material.use_nodes else None
        if tree is None:
            continue
        outputs = [node for node in tree.nodes if node.type == "OUTPUT_MATERIAL"]
        surface = next((node.inputs.get("Surface") for node in outputs if node.inputs.get("Surface") and node.inputs["Surface"].is_linked), None)
        if surface is None:
            continue
        exprs = {
            channel: _resolve_closure(surface, channel, created, cache, set())
            for channel in ("base_color", "roughness", "metallic")
        }
        row["channels"] = {
            channel: {"valid": bool(expr["valid"]), "source": expr["source"]}
            for channel, expr in exprs.items()
        }
        canonical = all(expr["valid"] and expr["socket"] is not None for expr in exprs.values())
        row["canonicalizable"] = canonical
        row["resolver"] = "mix_shader_reduced" if any(expr["source"] == "mix_shader" for expr in exprs.values()) else "reachable_surface"
        combine = tree.nodes.new("ShaderNodeCombineColor")
        created.append((tree, combine))
        for socket_name, expr in (("Red", exprs["roughness"]), ("Green", exprs["metallic"])):
            if expr["socket"] is not None:
                tree.links.new(expr["socket"], combine.inputs[socket_name])
        valid = _new_value(tree, 1.0 if canonical else 0.0, created)
        tree.links.new(valid, combine.inputs["Blue"])
        pbr_out, pbr_dst = _aov_output(tree, "GT_PBR_PARAMS", created, kind="color")
        tree.links.new(combine.outputs.get("Color") or combine.outputs[0], pbr_dst)
        if exprs["base_color"]["socket"] is not None:
            base_out, base_dst = _aov_output(tree, "GT_BASE_COLOR", created, kind="color")
            tree.links.new(exprs["base_color"]["socket"], base_dst)
        value = _new_value(tree, float(material_ids[material.name]), created)
        id_out, id_dst = _aov_output(tree, "GT_MaterialID", created, kind="value")
        tree.links.new(value, id_dst)
    return created


def _remove_nodes(created):
    for tree, item in reversed(_INTERFACES):
        try:
            tree.interface.remove(item)
        except Exception:
            pass
    _INTERFACES.clear()
    for tree, node in reversed(created):
        try:
            tree.nodes.remove(node)
        except Exception:
            pass


def _prepare_view_layer(view_layer):
    for name, kind in _AOVS.items():
        if view_layer.aovs.get(name) is None:
            aov = view_layer.aovs.add()
            aov.name = name
            aov.type = "COLOR" if kind == "color" else "VALUE"
    view_layer.use_pass_z = True
    view_layer.use_pass_normal = True
    view_layer.use_pass_object_index = True


def _setup_compositor(scene, out_dir: Path, frame_id: str):
    """Write modality-first PNG GT with packed and scalar PBR channels.

    The scalar maps are emitted as 16-bit grayscale PNGs.  The packed PBR map
    remains available for compatibility, while the artifact contract records
    the raw numeric encoding for every file.
    """
    scene.use_nodes = True
    tree = scene.node_tree
    tree.nodes.clear()
    layers = tree.nodes.new("CompositorNodeRLayers")
    outputs = {}

    def add_output(socket, stem: str):
        node = tree.nodes.new("CompositorNodeOutputFile")
        _base._configure_png_output(node, out_dir, frame_id, stem)
        tree.links.new(_base._encode_artifact_socket(tree, stem, socket), node.inputs[0])
        outputs[stem] = node

    for source, stem in (
        ("GT_BASE_COLOR", "base_color_rgb"),
        ("GT_PBR_PARAMS", "pbr_params"),
        ("GT_MaterialID", "material_id"),
        ("Normal", "normal_shading_camera"),
        ("Depth", "depth"),
        ("IndexOB", "object_id"),
    ):
        socket = layers.outputs.get(source)
        if socket is not None:
            add_output(socket, stem)

    packed = layers.outputs.get("GT_PBR_PARAMS")
    if packed is not None:
        separate = tree.nodes.new("CompositorNodeSepRGBA")
        tree.links.new(packed, separate.inputs[0])
        for component, stem in ((0, "roughness"), (1, "metallic"), (2, "pbr_validity")):
            combine = tree.nodes.new("CompositorNodeCombRGBA")
            for index in range(3):
                tree.links.new(separate.outputs[component], combine.inputs[index])
            combine.inputs[3].default_value = 1.0
            add_output(combine.outputs[0], stem)
    return outputs


def _collect_outputs(out_dir: Path, frame_id: str, _stems: list[str]):
    # The old exporter wrote an experimental all-zero geometry-normal AOV.
    # Remove only same-frame leftovers so a rerun cannot be mistaken for a
    # valid kitchen GT artifact.
    stale_paths = list(out_dir.glob(f"{frame_id}__normal_geometry_world*.exr"))
    geometry_dir = out_dir / "normal_geometry_world"
    if geometry_dir.is_dir():
        stale_paths.extend(geometry_dir.glob(f"{frame_id}*.png"))
    for stale in stale_paths:
        try:
            stale.unlink()
        except OSError:
            pass
    stems = [
        "base_color_rgb", "pbr_params", "roughness", "metallic", "pbr_validity",
        "normal_shading_camera", "depth", "object_id", "material_id",
    ]
    return _BASE_COLLECT_OUTPUTS(out_dir, frame_id, stems)


def _expand_default_viewpoints(argv: list[str]) -> list[str]:
    """Expand an omitted viewpoint list to every node heading in the graph."""
    if "--viewpoints" in argv:
        return argv
    if "--scene-graph" not in argv:
        return argv
    graph_path = Path(argv[argv.index("--scene-graph") + 1])
    graph = json.loads(graph_path.read_text(encoding="utf-8"))
    specs: list[str] = []
    for node in graph.get("nodes", []):
        node_id = str(node.get("node_id", ""))
        headings = node.get("headings") or [{"yaw_deg": 0.0}]
        for heading in headings:
            yaw = float(heading.get("yaw_deg", 0.0))
            specs.append(f"{node_id}@{yaw:g}")
    if not specs:
        raise ValueError(f"viewpoint graph contains no nodes: {graph_path}")
    print(f"[kitchen-gt] --viewpoints omitted; expanding {len(specs)} node headings", flush=True)
    return [*argv, "--viewpoints", ",".join(specs)]


def main() -> int:
    global _REPORT
    _REPORT = []
    raw_argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    expanded_argv = _expand_default_viewpoints(raw_argv)
    if expanded_argv != raw_argv:
        sys.argv = [sys.argv[0], "--", *expanded_argv]
    _base._AOVS = _AOVS
    _base._OUTPUT_STEMS = [
        "base_color_rgb", "pbr_params", "roughness", "metallic", "pbr_validity",
        "normal_shading_camera", "depth", "object_id", "material_id",
    ]
    _base._prepare_view_layer = _prepare_view_layer
    _base._install_material_aovs = _install_material_aovs
    _base._remove_nodes = _remove_nodes
    _base._setup_compositor = _setup_compositor
    _base._collect_outputs = _collect_outputs
    result = _base.main()
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    if "--out" in argv:
        out = Path(argv[argv.index("--out") + 1])
        table_path = out / "material_table.json"
        if table_path.is_file():
            payload = json.loads(table_path.read_text(encoding="utf-8"))
            payload["gt_aov_contract"] = {
                "schema": "robomituba.blender_kitchen_gt_aov.v2",
                "artifact_layout": _base._ARTIFACT_LAYOUT,
                "artifact_contract_ref": "gt_artifact_contract.json",
                "pbr_params": {"R": "roughness", "G": "metallic", "B": "validity"},
                "pbr_channel_files": {
                    "roughness": "roughness/{frame_id}.png (grayscale UNORM16)",
                    "metallic": "metallic/{frame_id}.png (grayscale UNORM16)",
                    "validity": "pbr_validity/{frame_id}.png (binary uint8)",
                },
                "base_color": "GT_BASE_COLOR",
                "normal": "normal_shading_camera",
                "invalid_closure_policy": "validity=0",
                "summary": {
                    "material_count": len(_REPORT),
                    "canonicalizable_count": sum(bool(row["canonicalizable"]) for row in _REPORT),
                    "invalid_count": sum(not bool(row["canonicalizable"]) for row in _REPORT),
                    "audit_closures": dict(sorted(Counter(row.get("audit_closure") for row in _REPORT).items())),
                    "resolvers": dict(sorted(Counter(row.get("resolver") for row in _REPORT).items())),
                    "channel_valid_counts": {
                        channel: sum(bool(row.get("channels", {}).get(channel, {}).get("valid")) for row in _REPORT)
                        for channel in ("base_color", "roughness", "metallic")
                    },
                },
                "materials": _REPORT,
            }
            table_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


if __name__ == "__main__":
    raise SystemExit(main())
