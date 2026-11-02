"""Split the merged LedPanelsFactory mesh of a frozen blend into one object per panel, name each ..._panel_NN, put them in a LedPanels collection, re-pair the lights (fixture_tags) and save.
(Future rounds already spawn one object per panel: room_planner/bookstore_ceiling.py.)

  run_bundled_blender.py --background IN.blend --python tools/infinigen/split_fixture_panels.py -- --out OUT.blend [--match LedPanelsFactory]

For every mesh object whose name contains --match (default LedPanelsFactory) and is not already a ..._panel_NN part: Separate by Loose Parts (every recessed square panel and every linear troffer is its own island), order the parts
along x then y, rename them <original name>_panel_NN (NN = 00, 01, ...), link them to the LedPanels collection. All lights lose their ir_fixture, then fixture_tags.apply runs again so each light
pairs with the part it sits in. Prints SPLIT_PANELS {...}. Writes OUT.blend (a copy); never overwrites IN unless OUT == IN.
"""
import argparse, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import bpy  # noqa: E402
import fixture_tags  # noqa: E402

ap = argparse.ArgumentParser(); ap.add_argument("--out", required=True); ap.add_argument("--match", default="LedPanelsFactory")
a = ap.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])
col = bpy.data.collections.get("LedPanels") or bpy.data.collections.new("LedPanels")
if col.name not in bpy.context.scene.collection.children:
    bpy.context.scene.collection.children.link(col)
split = {}
for o in [x for x in bpy.data.objects if x.type == "MESH" and a.match in x.name and "_panel_" not in x.name]:
    base = o.name
    bpy.ops.object.select_all(action="DESELECT"); bpy.context.view_layer.objects.active = o; o.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT"); bpy.ops.mesh.select_all(action="SELECT"); bpy.ops.mesh.separate(type="LOOSE"); bpy.ops.object.mode_set(mode="OBJECT")
    parts = [x for x in bpy.context.selected_objects if x.type == "MESH"]
    def centre(p):
        pts = [p.matrix_world @ __import__("mathutils").Vector(c) for c in p.bound_box]
        return (round(sum(q.x for q in pts) / 8, 2), round(sum(q.y for q in pts) / 8, 2))
    parts.sort(key=centre)
    for k, p in enumerate(parts):
        p.name = f"{base}_panel_{k:02d}"; p.data.name = p.name
        for c in list(p.users_collection):
            c.objects.unlink(p)
        col.objects.link(p)
        p["src"] = "arch:split_fixture_panels"
    split[base] = len(parts)
for L in bpy.data.objects:                                                     # re-pair every light: tags written before the split ("" for unpaired lights, or the merged name) must not block it
    if L.type == "LIGHT" and "ir_fixture" in L:
        del L["ir_fixture"]
stats = {}
stats["fixture_tags"] = fixture_tags.apply(stats)
print("SPLIT_PANELS", {"split": split, **stats["fixture_tags"]}, flush=True)
bpy.ops.wm.save_as_mainfile(filepath=str(Path(a.out).resolve()), copy=True)
