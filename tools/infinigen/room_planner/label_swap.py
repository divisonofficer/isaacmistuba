"""Swap the printed label of an Infinigen product (data/object_library_v2 package/*: FoodBox, FoodBag, Can, Bottle, Jar) for a pack_atlas design (abstract art, no real brands). The geometry is untouched: only the
material whose name contains "shader_text" (Infinigen's label shader, base colour = an image over the object's UVs) gets a unique copy with its image node pointed at atlas cell `k` (10 x 10, k = row * 10 + col from the top).
    swap(obj, k, rough=None) -> number of materials changed        works inside Blender (needs bpy)"""
import bpy
ATLAS = "/jarvis/project/robomituba/data/venue_refs/pack_atlas/pack_atlas.png"
N = 10


def swap(o, k, rough=None):
    img = bpy.data.images.load(ATLAS, check_existing=True); img.colorspace_settings.name = "sRGB"
    n = 0
    for ms in o.material_slots:
        m = ms.material
        if m is None or "shader_text" not in m.name or not m.use_nodes:
            continue
        m = m.copy(); m.name = f"{m.name}.pack{k}"; ms.material = m
        nt = m.node_tree; tx = next((x for x in nt.nodes if x.type == "TEX_IMAGE"), None); uvn = next((x for x in nt.nodes if x.type == "UVMAP"), None)
        if tx is None:
            continue
        tx.image = img; tx.interpolation = "Smart"; tx.extension = "EXTEND"
        mp = nt.nodes.new("ShaderNodeMapping"); mp.inputs["Scale"].default_value = (1.0 / N, 1.0 / N, 1.0)
        mp.inputs["Location"].default_value = ((k % N) / N, 1.0 - (k // N + 1) / N, 0.0)
        for l in list(tx.inputs["Vector"].links):
            nt.links.remove(l)
        if uvn is not None:
            nt.links.new(uvn.outputs["UV"], mp.inputs["Vector"])
        nt.links.new(mp.outputs["Vector"], tx.inputs["Vector"])
        if rough is not None:
            b = next((x for x in nt.nodes if x.type == "BSDF_PRINCIPLED"), None)
            if b is not None:
                for l in list(b.inputs["Roughness"].links):
                    nt.links.remove(l)
                b.inputs["Roughness"].default_value = rough
        n += 1
    return n
