"""ABO product models as Infinigen-style factories for the activity pass (user 2026-10-14: inject ABO assets as a post-process).

/bean/ir_dataset/abo_v1 (CC BY 4.0): 7,953 GLBs with PBR textures and an index (extent, triangles, emissive). A factory picks a
model of its product types by seed, imports the GLB once per scene, joins it into one mesh named
`<Factory>(<asin>).spawn_asset(<i>)` (so the activity pass treats it like any spawned asset), and hands out linked copies after that.

Orientation-free decor only for now (vases, planters, boxes, candle holders, table lamps): ABO models have no recorded front.
"""
from __future__ import annotations

import json
import os
import random
from pathlib import Path

import bpy
from mathutils import Matrix

INDEX = Path("/bean/ir_dataset/abo_v1/abo_object_index.json")
#: opt-in extra indexes in the same schema (e.g. vendor_datasets/polyhaven_models/polyhaven_object_index.json), os.pathsep-separated;
#: unset = ABO only, so seeds already built keep their picks
EXTRA_INDEXES = [Path(x) for x in os.environ.get("ROOM_EXTRA_ASSET_INDEXES", "").split(os.pathsep) if x]
MAX_TRIANGLES = 300_000
MAX_TEXTURE_PX = 1024
_entries: list | None = None
_imported: dict = {}            # asin -> imported mesh data (objects built on it share it; the mesh outlives a removed object)


def entries() -> list:
    global _entries
    if _entries is None:
        _entries = json.loads(INDEX.read_text())["objects"]
        for extra in EXTRA_INDEXES:
            _entries += json.loads(extra.read_text())["objects"]
    return _entries


#: share of picks per asset source (user 2026-10-16); ABO entries carry no "source". A source with nothing in a pool drops out
#: and the rest are renormalised. NVIDIA joins only after its MDL conversion is validated.
SOURCE_SHARE = {"abo": 0.45, "hssd": 0.30, "polyhaven": 0.25}


def pick(rng, pool: list) -> dict:
    """One entry of `pool`: a source by SOURCE_SHARE, then uniform within it. An ABO-only pool is a plain rng.choice, so seeds
    built before extra sources existed keep their picks."""
    by = {}
    for e in pool:
        by.setdefault(e.get("source", "abo"), []).append(e)
    if len(by) == 1:
        return rng.choice(pool)
    srcs = sorted(by)
    src = rng.choices(srcs, weights=[SOURCE_SHARE.get(s, 0.0) or 1e-9 for s in srcs])[0]
    return rng.choice(by[src])


def _import(entry: dict, name: str) -> bpy.types.Object:
    mesh = _imported.get(entry["id"])
    if mesh is not None:
        o = bpy.data.objects.new(name, mesh)
        bpy.context.scene.collection.objects.link(o)
        return o
    if not hasattr(bpy.ops.import_scene, "gltf"):
        bpy.ops.preferences.addon_enable(module="io_scene_gltf2")
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=entry["path"])
    new = [o for o in bpy.data.objects if o not in before]
    meshes = [o for o in new if o.type == "MESH"]
    for m in meshes:                                  # bake the glTF hierarchy (Y-up root etc.) into the vertices
        m.data = m.data.copy() if m.data.users > 1 else m.data
        m.data.transform(m.matrix_world)
        m.parent = None
        m.matrix_world = Matrix.Identity(4)
    for o in new:
        if o.type != "MESH":
            bpy.data.objects.remove(o, do_unlink=True)
    bpy.ops.object.select_all(action="DESELECT")
    for m in meshes:
        m.select_set(True)
    bpy.context.view_layer.objects.active = meshes[0]
    if len(meshes) > 1:
        bpy.ops.object.join()
    o = bpy.context.view_layer.objects.active
    o.name = name
    o.rotation_mode = "XYZ"                           # the glTF importer leaves QUATERNION, which ignores rotation_euler writes
    k = max(entry["extent_m"]) / max(max(o.dimensions), 1e-6)     # some GLBs carry a node scale the index does not
    if not 0.8 < k < 1.25:                                         # (a 0.33 m storage cube imported at 1.93 m): trust the index
        o.data.transform(Matrix.Scale(k, 4))
    for slot in o.material_slots:                     # 4K product textures cost render memory for 10 cm objects
        if slot.material and slot.material.node_tree:
            for n in slot.material.node_tree.nodes:
                img = getattr(n, "image", None)
                if img is not None and max(img.size) > MAX_TEXTURE_PX:
                    s = MAX_TEXTURE_PX / max(img.size)
                    img.scale(max(1, int(img.size[0] * s)), max(1, int(img.size[1] * s)))
                    try:
                        img.pack()                                    # a scaled image is an in-memory buffer: unpacked it is NOT saved with the blend and reloads empty -> pure white leaves / products (O2 r24 HSSD plants)
                    except Exception:                                 # noqa: BLE001
                        pass
    for slot in o.material_slots:                     # HSSD: inferred materials render with the HSSD pipeline's constant MR
        mr = (entry.get("mr_override") or {}).get(slot.material.name.split(".")[0] if slot.material else "")
        p = next((n for n in slot.material.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None) if mr and slot.material.node_tree else None
        if p is not None:
            for sock, v in (("Roughness", mr["roughness"]), ("Metallic", mr["metallic"])):
                for link in list(p.inputs[sock].links):
                    slot.material.node_tree.links.remove(link)
                p.inputs[sock].default_value = v
    _imported[entry["id"]] = o.data
    return o


def factory(cls_name: str, product_types: tuple, *, max_extent=0.45, min_height=0.0, max_height=9.0, emissive=False):
    """A factory class over the ABO models of `product_types` that fit the size filter."""
    pool = [e for e in entries() if e["product_type"] in product_types and max(e["extent_m"]) <= max_extent
            and min_height <= e["extent_m"][1] <= max_height and e["triangles"] <= MAX_TRIANGLES
            and (emissive or not e.get("emissive_materials"))]

    class AboFactory:
        def __init__(self, seed):
            self.entry = pick(random.Random(seed), pool)

        def spawn_asset(self, i):
            return _import(self.entry, f"{cls_name}({self.entry['id']}).spawn_asset({i})")

    AboFactory.__name__ = cls_name
    AboFactory.pool_size = len(pool)
    return AboFactory


VASE = factory("AboVaseFactory", ("VASE",))
PLANTER = factory("AboPlanterFactory", ("PLANTER",))
BOX = factory("AboStorageBoxFactory", ("STORAGE_BOX",))
CANDLE = factory("AboCandleHolderFactory", ("CANDLE_HOLDER",), emissive=False)
TABLE_LAMP = factory("AboTableLampFactory", ("LAMP",), max_extent=0.8, min_height=0.3, max_height=0.75)   # glTF Y is height
PILLOW = factory("AboPillowFactory", ("PILLOW",), max_extent=0.7)          # throw pillows; body pillows (>1 m) excluded
