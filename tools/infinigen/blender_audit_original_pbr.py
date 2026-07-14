#!/usr/bin/env python3
"""Audit original Infinigen Blender materials without mutating the scene.

Run through ``tools/infinigen/_run_bpy.py``.  The output deliberately separates
source-graph meaning from exporter artifacts: a PNG is evidence of an attempted
bake, not evidence that the source channel varied or that the bake is faithful.
"""

from __future__ import annotations

import argparse
import json
import math
import os
from collections import Counter, defaultdict

import bpy


CHANNELS = {
    "albedo": ("Base Color",),
    "roughness": ("Roughness",),
    "metallic": ("Metallic",),
    "normal": ("Normal",),
}

KNOWN_DEFAULTS = {
    "albedo": (0.8, 0.8, 0.8, 1.0),
    "roughness": 0.5,
    "metallic": 0.0,
}

PROCEDURAL_TYPES = {
    "TEX_NOISE", "TEX_VORONOI", "TEX_WAVE", "TEX_MUSGRAVE", "TEX_BRICK",
    "TEX_GRADIENT", "TEX_MAGIC", "TEX_CHECKER", "TEX_SKY", "TEX_WHITE_NOISE",
}
MIX_TYPES = {"MIX", "MIX_RGB", "MATH", "VALTORGB", "VECTOR_MATH", "MAP_RANGE"}
GEOMETRY_TYPES = {"NEW_GEOMETRY", "FRESNEL", "LAYER_WEIGHT", "AMBIENT_OCCLUSION", "BEVEL"}
ATTRIBUTE_TYPES = {"ATTRIBUTE", "VERTEX_COLOR", "UVMAP", "TANGENT"}
NONSTANDARD_SHADER_TYPES = {
    "BSDF_GLASS", "BSDF_REFRACTION", "BSDF_TRANSLUCENT", "BSDF_TRANSPARENT",
    "BSDF_DIFFUSE", "BSDF_GLOSSY", "BSDF_ANISOTROPIC", "BSDF_VELVET",
    "BSDF_HAIR", "BSDF_HAIR_PRINCIPLED", "SUBSURFACE_SCATTERING", "EMISSION",
    "HOLDOUT", "VOLUME_ABSORPTION", "VOLUME_SCATTER", "PRINCIPLED_VOLUME",
}


def _args():
    p = argparse.ArgumentParser()
    p.add_argument("--manifest", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--limit", type=int, default=0)
    return p.parse_args()


def _json_value(value):
    if isinstance(value, (bool, int, float, str)) or value is None:
        return value
    try:
        return [float(x) for x in value]
    except (TypeError, ValueError):
        return str(value)


def _close(a, b, eps=1e-5):
    if isinstance(a, list) and isinstance(b, (list, tuple)):
        return len(a) >= len(b) and all(abs(float(x) - float(y)) <= eps for x, y in zip(a, b))
    try:
        return abs(float(a) - float(b)) <= eps
    except (TypeError, ValueError):
        return False


def _all_nested_nodes(tree, seen=None, path="material"):
    if tree is None:
        return
    seen = set() if seen is None else seen
    key = tree.as_pointer()
    if key in seen:
        return
    seen.add(key)
    for node in tree.nodes:
        yield node, f"{path}/{node.name}"
        if node.type == "GROUP" and getattr(node, "node_tree", None):
            yield from _all_nested_nodes(node.node_tree, seen, f"{path}/{node.name}")


def _principled_occurrences(tree, seen=None, path="material", bindings=None):
    """Yield Principled instances with bindings for nested Group Input sockets."""
    if tree is None:
        return
    seen = set() if seen is None else set(seen)
    key = tree.as_pointer()
    if key in seen:
        return
    seen.add(key)
    bindings = {} if bindings is None else bindings
    for node in tree.nodes:
        node_path = f"{path}/{node.name}"
        if node.type == "BSDF_PRINCIPLED":
            yield node, node_path, bindings
        elif node.type == "GROUP" and getattr(node, "node_tree", None):
            child = {}
            for inp in node.inputs:
                child[inp.identifier] = (inp, bindings)
                child[inp.name] = (inp, bindings)
            yield from _principled_occurrences(node.node_tree, seen, node_path, child)


def _reachable_from_socket(socket, bindings=None, seen=None, path="surface"):
    """Yield nodes actually reachable upstream from a material output socket."""
    bindings = {} if bindings is None else bindings
    seen = set() if seen is None else seen
    for link in getattr(socket, "links", ()):
        node = link.from_node
        node_path = f"{path}/{node.name}"
        key = (node.as_pointer(), node_path, link.from_socket.identifier)
        if key in seen:
            continue
        seen.add(key)
        if node.type == "GROUP_INPUT":
            binding = bindings.get(link.from_socket.identifier) or bindings.get(link.from_socket.name)
            if binding is not None:
                outer, parent_bindings = binding
                yield from _reachable_from_socket(outer, parent_bindings, seen, node_path)
            continue
        if node.type == "GROUP" and getattr(node, "node_tree", None):
            child = {}
            for inp in node.inputs:
                child[inp.identifier] = (inp, bindings)
                child[inp.name] = (inp, bindings)
            for gout in (n for n in node.node_tree.nodes if n.type == "GROUP_OUTPUT"):
                target = gout.inputs.get(link.from_socket.identifier) or gout.inputs.get(link.from_socket.name)
                if target is not None:
                    yield from _reachable_from_socket(target, child, seen, node_path)
                    break
            continue
        yield node, node_path, bindings
        for inp in getattr(node, "inputs", ()):
            if inp.is_linked:
                yield from _reachable_from_socket(inp, bindings, seen, node_path)


def _upstream_features(socket, bindings=None, seen=None):
    """Conservative recursive source classification for one input socket."""
    seen = set() if seen is None else seen
    bindings = {} if bindings is None else bindings
    features, evidence, constants = set(), [], []
    for link in getattr(socket, "links", ()):
        node = link.from_node
        key = (node.as_pointer(), link.from_socket.identifier)
        if key in seen:
            continue
        seen.add(key)
        ntype = node.type
        evidence.append({"node": node.name, "type": ntype, "output": link.from_socket.name})
        if ntype == "GROUP_INPUT":
            binding = bindings.get(link.from_socket.identifier) or bindings.get(link.from_socket.name)
            if binding is None:
                features.add("UNRESOLVED")
            else:
                outer, parent_bindings = binding
                if outer.is_linked:
                    sub, sub_evidence, sub_constants = _upstream_features(outer, parent_bindings, seen)
                    features.update(sub); evidence.extend(sub_evidence); constants.extend(sub_constants)
                else:
                    constants.append(_json_value(outer.default_value))
            continue
        if ntype == "GROUP" and getattr(node, "node_tree", None):
            child_bindings = {}
            for inp in node.inputs:
                child_bindings[inp.identifier] = (inp, bindings)
                child_bindings[inp.name] = (inp, bindings)
            group_outputs = [n for n in node.node_tree.nodes if n.type == "GROUP_OUTPUT"]
            target = None
            for gout in group_outputs:
                target = gout.inputs.get(link.from_socket.identifier) or gout.inputs.get(link.from_socket.name)
                if target is not None:
                    break
            if target is None:
                features.add("UNRESOLVED")
            elif target.is_linked:
                sub, sub_evidence, sub_constants = _upstream_features(target, child_bindings, seen)
                features.update(sub); evidence.extend(sub_evidence); constants.extend(sub_constants)
            else:
                constants.append(_json_value(target.default_value))
            continue
        if ntype == "TEX_IMAGE":
            features.add("IMAGE_TEXTURE")
        elif ntype in ATTRIBUTE_TYPES:
            features.add("VERTEX_ATTRIBUTE")
        elif ntype in GEOMETRY_TYPES:
            features.add("GEOMETRY_DERIVED")
        elif ntype == "TEX_COORD":
            out = link.from_socket.name.upper()
            if out == "UV":
                features.add("PROCEDURAL_2D")
            elif out in {"OBJECT", "GENERATED", "NORMAL", "REFLECTION", "CAMERA", "WINDOW"}:
                features.add("PROCEDURAL_3D")
            else:
                features.add("GEOMETRY_DERIVED")
        elif ntype in PROCEDURAL_TYPES:
            features.add("PROCEDURAL_3D")
        elif ntype in {"RGB", "VALUE"}:
            constants.append(_json_value(link.from_socket.default_value))
        for inp in getattr(node, "inputs", ()):
            if inp.is_linked:
                sub, sub_evidence, sub_constants = _upstream_features(inp, bindings, seen)
                features.update(sub)
                evidence.extend(sub_evidence)
                constants.extend(sub_constants)
        if ntype in MIX_TYPES and len(features) > 1:
            features.add("MIXED")
    return features, evidence[:40], constants


def _classify_socket(channel, socket, bindings=None):
    if channel == "normal" and not socket.is_linked:
        return {"state": "ABSENT", "value": _json_value(socket.default_value), "evidence": [], "features": [], "linked": False}
    if not socket.is_linked:
        value = _json_value(socket.default_value)
        state = "DEFAULT_CONSTANT" if _close(value, KNOWN_DEFAULTS[channel]) else "EXPLICIT_CONSTANT"
        return {"state": state, "value": value, "evidence": [], "features": [], "linked": False}
    features, evidence, constants = _upstream_features(socket, bindings)
    useful = features - {"MIXED"}
    if not useful and constants:
        value = constants[0]
        different = len({json.dumps(v, sort_keys=True) for v in constants}) > 1
        if channel == "normal":
            state = "ABSENT"
        else:
            state = "MIXED" if different else (
                "DEFAULT_CONSTANT" if _close(value, KNOWN_DEFAULTS[channel]) else "EXPLICIT_CONSTANT"
            )
        return {"state": state, "value": value, "evidence": evidence, "features": [], "linked": True}
    if not useful:
        state = "UNRESOLVED"
    elif "MIXED" in features or len(useful) > 1 or constants:
        state = "MIXED"
    else:
        state = next(iter(useful))
    return {"state": state, "value": None, "evidence": evidence, "features": sorted(features), "linked": True}


def _aggregate_channel(channel, records):
    if not records:
        return {"state": "ABSENT" if channel == "normal" else "UNRESOLVED", "members": []}
    states = {r["state"] for r in records}
    values = {json.dumps(r.get("value"), sort_keys=True) for r in records if "CONSTANT" in r["state"]}
    state = next(iter(states)) if len(states) == 1 and len(values) <= 1 else "MIXED"
    return {"state": state, "members": records}


def _socket(node, *names):
    for name in names:
        s = node.inputs.get(name)
        if s is not None:
            return s
    return None


def _active_value(socket, inactive=0.0, eps=1e-5):
    if socket is None:
        return False
    if socket.is_linked:
        return True
    value = _json_value(socket.default_value)
    if isinstance(value, list):
        return any(abs(float(x) - inactive) > eps for x in value[:3])
    return abs(float(value) - inactive) > eps


def _material_audit(material):
    if material is None:
        return {"name": None, "closure": "MISSING_MATERIAL", "channels": {}, "features": ["missing_material"]}
    if not material.use_nodes or material.node_tree is None:
        return {"name": material.name, "closure": "LEGACY_MATERIAL", "channels": {}, "features": ["legacy_material"]}
    output_nodes = [n for n in material.node_tree.nodes if n.type == "OUTPUT_MATERIAL"]
    nodes = list(_all_nested_nodes(material.node_tree))
    types = Counter(n.type for n, _ in nodes)
    surface_nodes = []
    for output in output_nodes:
        surface = output.inputs.get("Surface")
        if surface is not None and surface.is_linked:
            surface_nodes.extend(_reachable_from_socket(surface))
    surface_types = Counter(n.type for n, _, _ in surface_nodes)
    principled = [(n, p, b) for n, p, b in surface_nodes if n.type == "BSDF_PRINCIPLED"]
    features = set()
    if any((n.inputs.get("Displacement") and n.inputs["Displacement"].is_linked) for n in output_nodes):
        features.add("displacement")
    if any((n.inputs.get("Volume") and n.inputs["Volume"].is_linked) for n in output_nodes):
        features.add("volume")
    if surface_types["MIX_SHADER"] or surface_types["ADD_SHADER"] or len(principled) > 1:
        features.add("layered_shader")
    if any(t in surface_types for t in NONSTANDARD_SHADER_TYPES):
        features.add("nonstandard_closure")
    for node, _, _ in principled:
        if _active_value(_socket(node, "Transmission Weight", "Transmission")):
            features.add("transmission")
        if _active_value(_socket(node, "Alpha"), inactive=1.0):
            features.add("alpha")
        if _active_value(_socket(node, "Coat Weight", "Clearcoat")):
            features.add("coat")
        if _active_value(_socket(node, "Sheen Weight", "Sheen")):
            features.add("sheen")
        if _active_value(_socket(node, "Subsurface Weight", "Subsurface")):
            features.add("subsurface")
        if _active_value(_socket(node, "Emission Strength")):
            features.add("emission")
        aniso = _socket(node, "Anisotropic", "Anisotropy")
        if aniso is not None and _active_value(aniso):
            features.add("anisotropy")
    channels = {}
    for channel, names in CHANNELS.items():
        records = []
        for node, path, bindings in principled:
            s = _socket(node, *names)
            if s is not None:
                rec = _classify_socket(channel, s, bindings)
                rec["path"] = path
                records.append(rec)
        channels[channel] = _aggregate_channel(channel, records)
    if not output_nodes or not any(n.inputs.get("Surface") and n.inputs["Surface"].is_linked for n in output_nodes):
        closure = "MISSING_SURFACE"
    elif len(principled) == 1 and not ({"layered_shader", "nonstandard_closure"} & features):
        closure = "PRINCIPLED_SINGLE"
    elif principled:
        closure = "PRINCIPLED_LAYERED"
    else:
        closure = "NON_PRINCIPLED"
    return {
        "name": material.name,
        "closure": closure,
        "channels": channels,
        "features": sorted(features),
        "node_type_counts": dict(sorted(types.items())),
        "reachable_surface_node_type_counts": dict(sorted(surface_types.items())),
        "principled_count": len(principled),
        "blend_method": getattr(material, "surface_render_method", getattr(material, "blend_method", None)),
    }


def _uv_audit(mesh):
    layers = list(mesh.uv_layers)
    active = mesh.uv_layers.active
    result = {"layers": [x.name for x in layers], "active": active.name if active else None, "valid": False}
    if not active or not active.data:
        return result
    us, vs = [], []
    for loop in active.data:
        u, v = loop.uv
        if math.isfinite(u) and math.isfinite(v):
            us.append(float(u)); vs.append(float(v))
    nonzero_area = 0
    sampled_triangles = 0
    try:
        mesh.calc_loop_triangles()
        step = max(1, len(mesh.loop_triangles) // 4000)
        for index in range(0, len(mesh.loop_triangles), step):
            loops = mesh.loop_triangles[index].loops
            uv0, uv1, uv2 = (active.data[i].uv for i in loops)
            area2 = abs(
                (uv1.x - uv0.x) * (uv2.y - uv0.y)
                - (uv1.y - uv0.y) * (uv2.x - uv0.x)
            )
            sampled_triangles += 1
            if math.isfinite(area2) and area2 > 1e-10:
                nonzero_area += 1
    except Exception:  # noqa: BLE001
        pass
    result.update({
        "valid": bool(us and nonzero_area),
        "finite_loops": len(us),
        "sampled_triangles": sampled_triangles,
        "sampled_nonzero_uv_area_triangles": nonzero_area,
        "u_range": [min(us), max(us)] if us else None,
        "v_range": [min(vs), max(vs)] if vs else None,
    })
    return result


def _geometry_nodes_audit(obj):
    out = []
    for mod in obj.modifiers:
        if mod.type != "NODES" or not getattr(mod, "node_group", None):
            continue
        types = Counter(n.type for n, _ in _all_nested_nodes(mod.node_group, path=f"modifier/{mod.name}"))
        out.append({
            "modifier": mod.name,
            "node_type_counts": dict(sorted(types.items())),
            "material_dependent": any(k in types for k in {"SET_MATERIAL", "STORE_NAMED_ATTRIBUTE", "INPUT_MATERIAL"}),
            "instance_dependent": any(k in types for k in {"INSTANCE_ON_POINTS", "GEOMETRY_TO_INSTANCE", "REALIZE_INSTANCES"}),
        })
    return out


def _manifest_channel(unit, channel):
    key = "base_color" if channel == "albedo" else channel
    rec = (((unit.get("pbr") or {}).get("channels") or {}).get(key) or {})
    return {
        "mode": rec.get("mode"), "texture": rec.get("ref"), "constant": rec.get("value"),
        "source": rec.get("source"),
        "bake_validation": rec.get("bake_validation"),
    }


def _primary_group(materials, uv_valid, gn):
    features = {f for m in materials for f in m.get("features", [])}
    closures = {m.get("closure") for m in materials}
    states = {c["state"] for m in materials for c in m.get("channels", {}).values()}
    if "MISSING_SURFACE" in closures:
        return "G7_BAKE_FAILURE_OR_INVALID"
    if closures == {"MISSING_MATERIAL"}:
        return "G1_STANDARD_PBR_WITH_CONSTANTS"
    if gn:
        return "G6_EVALUATED_MESH_DEPENDENT"
    if {"transmission", "volume", "alpha"} & features:
        return "G4_TRANSMISSION_GLASS"
    if "nonstandard_closure" in features or "layered_shader" in features:
        return "G5_NONSTANDARD_OR_LAYERED"
    if "displacement" in features:
        return "G3_DISPLACEMENT_DEPENDENT"
    if states & {"PROCEDURAL_2D", "PROCEDURAL_3D", "VERTEX_ATTRIBUTE", "GEOMETRY_DERIVED", "MIXED"}:
        return "G2_BAKEABLE_PROCEDURAL_PBR"
    if states & {"DEFAULT_CONSTANT", "EXPLICIT_CONSTANT", "ABSENT"}:
        return "G1_STANDARD_PBR_WITH_CONSTANTS"
    return "G0_COMPLETE_STANDARD_VARYING_ARMN"


def _fidelity(group, unit, material_features):
    channels = {k: _manifest_channel(unit, k) for k in CHANNELS}
    collapse_known = any(v["mode"] == "texture" and not v["texture"] for v in channels.values())
    if group == "G7_BAKE_FAILURE_OR_INVALID" or collapse_known:
        return "unsupported"
    if group in {"G3_DISPLACEMENT_DEPENDENT", "G4_TRANSMISSION_GLASS", "G5_NONSTANDARD_OR_LAYERED"}:
        return "severely_lossy"
    if group == "G6_EVALUATED_MESH_DEPENDENT":
        return "acceptable_approximation"
    if group == "G2_BAKEABLE_PROCEDURAL_PBR":
        return "bake_equivalent_candidate"
    if material_features & {"coat", "sheen", "subsurface", "emission", "anisotropy"}:
        return "acceptable_approximation"
    return "exact_candidate"


def main():
    args = _args()
    with open(args.manifest, "r", encoding="utf-8") as f:
        manifest = json.load(f)
    manifest_by_name = {u.get("blender_name"): u for u in manifest.get("units", [])}
    objects = [o for o in bpy.data.objects if o.type == "MESH" and len(o.data.polygons)]
    objects.sort(key=lambda o: o.name)
    if args.limit > 0:
        objects = objects[:args.limit]
    depsgraph = bpy.context.evaluated_depsgraph_get()
    material_cache = {}
    rows = []
    for index, obj in enumerate(objects, 1):
        placeholder = "placeholder" in obj.name.lower() or any(
            "placeholder" in c.name.lower() for c in obj.users_collection
        )
        exporter_renderable = not placeholder
        mats = []
        for slot in obj.material_slots:
            mat = slot.material
            key = mat.as_pointer() if mat else 0
            if key not in material_cache:
                material_cache[key] = _material_audit(mat)
            mats.append(material_cache[key])
        if not mats:
            mats = [_material_audit(None)]
        evaluated = {"vertices": None, "polygons": None, "error": None, "skipped": False}
        if placeholder:
            evaluated["skipped"] = True
            evaluated["error"] = "excluded placeholder duplicate"
        else:
            try:
                eval_obj = obj.evaluated_get(depsgraph)
                eval_mesh = eval_obj.to_mesh()
                evaluated.update({"vertices": len(eval_mesh.vertices), "polygons": len(eval_mesh.polygons)})
                eval_obj.to_mesh_clear()
            except Exception as exc:  # noqa: BLE001
                evaluated["error"] = str(exc)
        gn = _geometry_nodes_audit(obj)
        unit = manifest_by_name.get(obj.name, {})
        features = {f for m in mats for f in m.get("features", [])}
        uv = _uv_audit(obj.data)
        group = _primary_group(mats, uv["valid"], gn)
        rows.append({
            "name": obj.name,
            "manifest_unit_id": unit.get("id"),
            "in_manifest": bool(unit),
            "exporter_renderable": exporter_renderable,
            "export_exclusion_reason": "placeholder duplicate" if placeholder else None,
            "visibility": {
                "hide_render": bool(obj.hide_render), "hide_viewport": bool(obj.hide_viewport),
                "hide_get": bool(obj.hide_get()),
                "collections": [c.name for c in obj.users_collection],
            },
            "geometry": {
                "source_vertices": len(obj.data.vertices), "source_polygons": len(obj.data.polygons),
                "evaluated": evaluated,
                "modifiers": [{"name": m.name, "type": m.type, "show_render": bool(m.show_render)} for m in obj.modifiers],
                "geometry_nodes": gn,
            },
            "uv": uv,
            "materials": mats,
            "source_features": sorted(features),
            "manifest_channels": {k: _manifest_channel(unit, k) for k in CHANNELS},
            "exportability_group": group,
            "fidelity_provisional": _fidelity(group, unit, features),
            "validation_required": "original_vs_baked_multiview_render",
        })
        if index % 20 == 0:
            print(f"[original-pbr-audit] {index}/{len(objects)}", flush=True)
    core = [r for r in rows if r["exporter_renderable"]]
    placeholders = [r for r in rows if not r["exporter_renderable"]]
    summary = {
        "source_blend": bpy.data.filepath,
        "manifest": os.path.abspath(args.manifest),
        "object_count": len(rows),
        "exporter_renderable_count": len(core),
        "placeholder_duplicate_count": len(placeholders),
        "manifest_match_count": sum(r["in_manifest"] for r in core),
        "render_visible_count": sum(not r["visibility"]["hide_render"] for r in rows),
        "exportability_groups": dict(sorted(Counter(r["exportability_group"] for r in core).items())),
        "fidelity_provisional": dict(sorted(Counter(r["fidelity_provisional"] for r in core).items())),
        "source_feature_counts": dict(sorted(Counter(f for r in core for f in r["source_features"]).items())),
        "channel_source_states": {
            ch: dict(sorted(Counter(
                m.get("channels", {}).get(ch, {}).get("state", "UNRESOLVED")
                for r in core for m in r["materials"]
            ).items())) for ch in CHANNELS
        },
        "method_limitations": [
            "Fidelity labels ending in _candidate require original-vs-baked multiview render comparison.",
            "Nested group traversal is conservative: unrelated nodes inside a group can make a source MIXED.",
            "Manifest texture existence is not treated as proof of meaningful covered-UV variation.",
        ],
    }
    result = {"schema": "robomituba.infinigen.original_pbr_audit.v1", "summary": summary, "objects": rows}
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
