"""Explicit optical derivatives for locally imported native Blender assets.

Callers supply exact canonical registry records after identifying the surface.
Registry values may be inferred; this module does not certify measured BRDFs.
It does not edit native geometry, UVs, images or source material datablocks.
"""

import math

import bpy


def derive_invalid_native_ior(original, tag, assumed_ior=1.5):
    """Copy an inspected product material whose unlinked IOR is below one.

    The caller must identify an ordinary physical product surface first. This
    is an explicit optical assumption, not a source-unit or material inference.
    Metallic, roughness and normal maps remain connected and unchanged.
    """
    value = float(assumed_ior)
    if not math.isfinite(value) or value < 1:
        raise ValueError("Assumed physical IOR must be finite and at least one")
    nodes = (
        [node for node in original.node_tree.nodes if node.type == "BSDF_PRINCIPLED"]
        if original.use_nodes
        else []
    )
    if len(nodes) != 1:
        raise ValueError("Requires one explicitly inspected Principled node")
    node = nodes[0]
    socket = node.inputs["IOR"]
    prior = float(socket.default_value)
    if socket.is_linked or not math.isfinite(prior) or prior >= 1:
        raise ValueError("Requires an unlinked finite source IOR below one")
    derivative = original.copy()
    derivative.name = f"{tag}__{original.name}"
    derivative.node_tree.nodes[node.name].inputs["IOR"].default_value = value
    return derivative, {
        "source_material": original.name,
        "derivative_material": derivative.name,
        "prior_unlinked_values": {"IOR": prior},
        "applied_values": {"IOR": value},
        "ior_interpretation": "Explicit physical assumption; not measured optics",
        "metallic_roughness_and_normal_unchanged": True,
        "linked_maps_disconnected": False,
    }


def derive_native_material(original, asset_entry, canonical_name, tag):
    """Copy one inspected Principled material using an exact registry rule.

    Linked metallic/roughness maps require separate semantic inspection and are
    never disconnected here. Invalid ordinary dielectric IOR values are replaced
    by an explicitly assumed 1.5, not a manufacturer measurement.
    """
    rule = asset_entry.get("mr_override", {}).get(canonical_name)
    if rule is None:
        raise ValueError(f"No exact registry override: {canonical_name}")
    nodes = (
        [node for node in original.node_tree.nodes if node.type == "BSDF_PRINCIPLED"]
        if original.use_nodes
        else []
    )
    if len(nodes) != 1:
        raise ValueError("Requires one explicitly inspected Principled node")

    source_node = nodes[0]
    prior = {}
    changes = {}
    for socket, field in (("Metallic", "metallic"), ("Roughness", "roughness")):
        if field not in rule:
            continue
        value = float(rule[field])
        if not math.isfinite(value) or not 0 <= value <= 1:
            raise ValueError(f"Invalid registry {field}: {value}")
        if source_node.inputs[socket].is_linked:
            raise ValueError(f"Inspect linked physical map separately: {socket}")
        prior[socket] = float(source_node.inputs[socket].default_value)
        if prior[socket] != value:
            changes[socket] = value

    ior = source_node.inputs["IOR"]
    if not ior.is_linked and float(ior.default_value) < 1:
        prior["IOR"] = float(ior.default_value)
        changes["IOR"] = 1.5

    derivative = original.copy()
    derivative.name = f"{tag}__{canonical_name}"
    target_node = derivative.node_tree.nodes[source_node.name]
    for socket, value in changes.items():
        target_node.inputs[socket].default_value = value
    return derivative, {
        "source_material": original.name,
        "derivative_material": derivative.name,
        "canonical_registry_material": canonical_name,
        "asset_id": asset_entry["id"],
        "registry_rule": rule,
        "registry_pbr_provenance": [
            entry
            for entry in asset_entry.get("pbr", [])
            if entry.get("name") == canonical_name
        ],
        "prior_unlinked_values": prior,
        "applied_values": changes,
        "ior_interpretation": "Assumed dielectric 1.5; not measured optics",
        "linked_maps_disconnected": False,
    }


def apply_registry_optics_to_objects(objects, specifications, tag):
    """Apply explicit material specifications only to the requested objects.

    ``specifications`` maps exact original material names to
    ``(asset_entry, canonical_material_name)`` pairs. No name-prefix guessing is
    performed. Object overrides prevent a shared native mesh from changing an
    unselected instance. Exporters must resolve effective object material slots,
    rather than reading only ``mesh.materials``.
    """
    clones = {}
    material_receipts = []
    planned = []
    previous = []
    try:
        for obj in tuple(objects):
            if obj.library is not None:
                raise ValueError("Use local derivative objects, not linked sources")
            for index, slot in enumerate(obj.material_slots):
                material = slot.material
                if material is None or material.name not in specifications:
                    continue
                key = material.as_pointer()
                if key not in clones:
                    entry, canonical = specifications[material.name]
                    clone, receipt = derive_native_material(
                        material, entry, canonical, tag
                    )
                    clones[key] = clone
                    material_receipts.append(receipt)
                planned.append((obj, index, clones[key]))
                previous.append((obj, index, slot.link, material))
        if not planned:
            raise ValueError("No exact source material names matched the scope")

        # Resolve every original binding before touching shared instance state.
        for obj, index, clone in planned:
            slot = obj.material_slots[index]
            slot.link = "OBJECT"
            slot.material = clone
    except Exception:
        for obj, index, link, material in reversed(previous):
            slot = obj.material_slots[index]
            slot.link = link
            if link == "OBJECT":
                slot.material = material
        for clone in clones.values():
            if clone.users - int(clone.use_fake_user) == 0:
                bpy.data.materials.remove(clone)
        raise

    return {
        "material_derivatives": material_receipts,
        "assignments": [
            {"object": obj.name, "slot": index, "material": clone.name}
            for obj, index, clone in planned
        ],
        "assignment_scope": "Requested objects only; shared mesh arrays untouched",
        "export_contract": "Resolve effective per-object material slots",
        "measured_material_certification": False,
    }
